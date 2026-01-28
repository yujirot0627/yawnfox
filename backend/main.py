# app/main.py
import json
import uuid
import time
import asyncio
import logging
from typing import Dict, Set, Optional
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Route
from starlette.websockets import WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("yawnfox")

# --- Global State ---
websockets: Dict[str, "ManagedWebSocket"] = {}
partners: Dict[str, str] = {}

# Structure: ws_id -> {"topics": frozenset({...}), "time": monotonic_time}
ready_clients: Dict[str, dict] = {}

match_event = asyncio.Event()
state_lock = asyncio.Lock()

# --- Helper Classes ---

class ManagedWebSocket:
    def __init__(self, websocket: WebSocket, ws_id: str, on_send_fail=None):
        self.websocket = websocket
        self.id = ws_id
        self.closed = False
        self.on_send_fail = on_send_fail  # callable(ws_id) -> None

    async def safe_close(self):
        if not self.closed:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.closed = True

    async def send_text(self, message: str):
        if self.closed:
            return
        try:
            await self.websocket.send_text(message)
        except Exception as e:
            logger.warning(f"[{self.id}] Send failed: {e}")
            self.closed = True
            # schedule cleanup (non-blocking)
            if self.on_send_fail:
                try:
                    self.on_send_fail(self.id)
                except Exception:
                    pass

# --- Core Logic ---

async def soft_unpair(ws_id: str):
    """
    Unpairs a user from their partner without closing the connection.
    Notifies the partner they have been left.
    MUST be called under state_lock if used in concurrent contexts.
    """
    partner_id = partners.pop(ws_id, None)
    if partner_id:
        partners.pop(partner_id, None)
        partner_ws = websockets.get(partner_id)
        if partner_ws:
            # Notify partner they are alone
            asyncio.create_task(partner_ws.send_text(json.dumps({"name": "PARTNER_LEFT"})))

async def matcher_loop():
    """Background task to match waiting clients."""
    logger.info("Matcher loop started.")
    while True:
        await match_event.wait()
        
        # Keep matching until no pairs can be formed
        while True:
            async with state_lock:
                if len(ready_clients) < 2:
                    match_event.clear()
                    break

                # Sort by time waiting (Oldest first) ensuring fairness
                sorted_clients = sorted(ready_clients.items(), key=lambda item: item[1]['time'])
                
                candidate_a_id, data_a = sorted_clients[0]
                topics_a = data_a['topics']
                
                best_match_id = None
                
                # 1. Try to find a topic overlap
                if topics_a:
                    for other_id, other_data in sorted_clients[1:]:
                        topics_b = other_data['topics']
                        if not topics_a.isdisjoint(topics_b):
                            best_match_id = other_id
                            break
                            
                # 2. Fallback: Pick the longest waiting available person (first in rest of list)
                if not best_match_id:
                    best_match_id = sorted_clients[1][0]

                # --- Execute Match ---
                # Remove from pool immediately
                wait_data_a = ready_clients.pop(candidate_a_id)
                wait_data_b = ready_clients.pop(best_match_id)
                
                ws_a = websockets.get(candidate_a_id)
                ws_b = websockets.get(best_match_id)

                # Check connection health before establishing
                if ws_a and not ws_a.closed and ws_b and not ws_b.closed:
                    partners[candidate_a_id] = best_match_id
                    partners[best_match_id] = candidate_a_id
                    
                    logger.info(f"Match formed: {candidate_a_id} <> {best_match_id}")

                    # Tasks for sending to avoid blocking lock/loop
                    asyncio.create_task(ws_a.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "GO_FIRST"})))
                    asyncio.create_task(ws_b.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "WAIT"})))
                else:
                    # Someone disconnected during match attempt, return survivor to pool priority
                    if ws_a and not ws_a.closed:
                        ready_clients[candidate_a_id] = wait_data_a
                    if ws_b and not ws_b.closed:
                        ready_clients[best_match_id] = wait_data_b
            
            # Brief yield to let other tasks run (like IO)
            await asyncio.sleep(0)


async def cleanup(ws_id: str):
    """Robust cleanup for a disconnecting user. Called on disconnect."""
    ws = None
    async with state_lock:
        # Guard: already cleaned
        ws = websockets.get(ws_id)
        if ws is None:
            return

        # Remove from wait pool
        ready_clients.pop(ws_id, None)

        # Unpair and notify partner
        await soft_unpair(ws_id)

        # Remove socket ref
        ws = websockets.pop(ws_id, None)

    if ws:
        await ws.safe_close()

    logger.info(f"[{ws_id}] Cleaned up.")

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_id = str(uuid.uuid4())
    ws = ManagedWebSocket(websocket, ws_id, on_send_fail=lambda _id: asyncio.create_task(cleanup(_id)))
    
    async with state_lock:
        websockets[ws_id] = ws
    
    logger.info(f"[{ws_id}] Connected.")

    try:
        while True:
            try:
                # Starlette handles timeouts internally if configured, no extra timeout needed here
                message = await websocket.receive_text()
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"[{ws_id}] Invalid JSON.")
                continue
            except WebSocketDisconnect:
                raise # handled in outer except
            except Exception as e:
                logger.error(f"[{ws_id}] Receive error: {e}")
                break

            msg_name = data.get("name")

            if msg_name == "PAIRING_START":
                async with state_lock:
                    # Ensure clean slate (using soft_unpair so we don't close current socket)
                    if ws_id in ready_clients:
                        del ready_clients[ws_id]
                    
                    await soft_unpair(ws_id)

                    # Parse topics
                    raw_topics = data.get("topics", [])
                    if not raw_topics and data.get("topic"):
                        raw_topics = [data.get("topic")]
                    
                    normalized_topics = frozenset(
                        str(t).strip().lower() 
                        for t in raw_topics 
                        if str(t).strip()
                    )

                    ready_clients[ws_id] = {
                        "topics": normalized_topics,
                        "time": time.monotonic()
                    }
                    
                    # Trigger matcher
                    match_event.set()

            elif msg_name == "PAIRING_ABORT":
                async with state_lock:
                    if ws_id in ready_clients:
                        del ready_clients[ws_id]
                    if len(ready_clients) < 2:
                        match_event.clear()

            elif msg_name == "LEAVE":
                # User manually signalling leave (next button)
                async with state_lock:
                    if ws_id in ready_clients:
                        del ready_clients[ws_id]
                    await soft_unpair(ws_id)

            elif msg_name == "CHAT":
                # CHAT is fire-and-forget
                partner_ws = None
                async with state_lock:
                    partner_id = partners.get(ws_id)
                    if partner_id:
                        partner_ws = websockets.get(partner_id)
                
                if partner_ws:
                    asyncio.create_task(partner_ws.send_text(json.dumps(data)))
            
        
            # Generic signaling relay (SDP, ICE candidates, etc.)
            # Order matters -> await send
            else:
                partner_ws = None
                async with state_lock:
                    partner_id = partners.get(ws_id)
                    if partner_id:
                        partner_ws = websockets.get(partner_id)

                if partner_ws:
                    await partner_ws.send_text(json.dumps(data))

    except WebSocketDisconnect:
        logger.info(f"[{ws_id}] Disconnected.")
    except Exception as e:
        logger.error(f"[{ws_id}] Unexpected error: {e}")
    finally:
        # GUARANTEED CLEANUP on any exit path
        await cleanup(ws_id)


# --- Lifecycle ---

@asynccontextmanager
async def lifespan(app: Starlette):
    # Startup
    logger.info("Server starting...")
    matcher_task = asyncio.create_task(matcher_loop())
    yield
    # Shutdown
    logger.info("Server shutting down...")
    matcher_task.cancel()
    try:
        await matcher_task
    except asyncio.CancelledError:
        pass

async def ping(request):
    return JSONResponse({"message": "Server is awake"})

app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/ping", ping),
        WebSocketRoute("/api/matchmaking", websocket_endpoint),
    ]
)
