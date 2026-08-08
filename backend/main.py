# app/main.py

# Must run before any other import: store.py resolves its configuration into
# module-level constants at import time (CONN_TTL, RATE_LIMIT_MAX, _inmemory_mode,
# ...), so loading the .env after `import store` would be too late for those.
# With no .env present this is a no-op — which is the case on Fly.io, where the
# values come from `fly secrets set`. See .env.example.
from dotenv import load_dotenv

load_dotenv()

import os
import json
import uuid
import asyncio
import logging
from typing import Dict, Optional
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Route
from starlette.websockets import WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

import store

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("yawnfox")

# --- Per-process state ---
# Only the live WebSocket objects are kept in memory; every piece of shared
# state (waiting pool, partner mapping, presence) lives in Redis (see store.py)
# so the app can run as multiple horizontally-scaled instances.
local_websockets: Dict[str, "ManagedWebSocket"] = {}

# Local matcher wake signal (also nudged across instances via Redis pub/sub).
match_event = asyncio.Event()

# Allowed browser origins for the signaling WebSocket and /ping (comma separated).
# Empty -> allow all (development).
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGIN", "").split(",") if o.strip()]

# Trust the X-Forwarded-For header for the client IP only when explicitly enabled.
# Default off: it is client-controllable and could be spoofed to evade the rate
# limiter. On Fly, fly-client-ip (set by the trusted proxy) is preferred anyway.
_trust_xff = os.environ.get("TRUST_XFF", "false").strip().lower() == "true"

# Maximum accepted WebSocket text frame (bytes). Also enforced at the protocol
# layer via uvicorn --ws-max-size; this is a belt-and-suspenders app-level guard.
MAX_MESSAGE_BYTES = 65536

# Message names that may be relayed verbatim to a partner (WebRTC signaling).
ALLOWED_RELAY = {"SDP_OFFER", "SDP_ANSWER", "SDP_ICE_CANDIDATE"}

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

# --- Delivery / helpers ---

async def deliver_local(ws_id: str, text: str) -> bool:
    """Deliver a raw text frame to a locally-connected client. Returns success."""
    ws = local_websockets.get(ws_id)
    if ws is None:
        return False
    await ws.send_text(text)
    return True


def _origin_allowed(origin: Optional[str]) -> bool:
    if not _cors_origins:
        return True  # not configured -> allow (dev)
    return bool(origin) and origin in _cors_origins


def _client_ip(websocket: WebSocket) -> str:
    headers = websocket.headers
    # Prefer the trusted-proxy header. Only fall back to X-Forwarded-For when
    # explicitly allowed (TRUST_XFF=true); otherwise use the raw peer address.
    fly_ip = headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip
    if _trust_xff:
        forwarded = headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return websocket.client.host if websocket.client else "unknown"


# --- Core Logic ---

async def soft_unpair(ws_id: str):
    """
    Unpairs a user from their partner without closing the connection.
    Notifies the partner they have been left.
    """
    partner_id = await store.clear_partner(ws_id)
    if partner_id:
        asyncio.create_task(store.route(partner_id, {"name": "PARTNER_LEFT"}))


async def matcher_loop():
    """Background task to match waiting clients (coordinated across instances
    by a Redis lock; every instance runs this so the matcher is not a SPOF)."""
    logger.info("Matcher loop started.")
    while True:
        try:
            # Wake on a local/cross-instance signal, or poll as a fallback.
            try:
                await asyncio.wait_for(match_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            match_event.clear()

            if await store.waiting_count() < 2:
                continue
            if not await store.try_acquire_matcher_lock():
                continue  # another instance is matching right now
            try:
                await store.run_matcher_rounds()
            finally:
                await store.release_matcher_lock()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Matcher loop error: {e}")
            await asyncio.sleep(0.5)


async def heartbeat_loop():
    """Periodically extend TTLs for this instance's live clients so idle
    waiting users are not garbage-collected, and dead instances self-heal."""
    while True:
        try:
            await asyncio.sleep(30)
            if local_websockets:
                await store.refresh(list(local_websockets.keys()))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")


async def cleanup(ws_id: str):
    """Robust cleanup for a disconnecting user. Called on any exit path."""
    ws = local_websockets.pop(ws_id, None)

    # Unpair and notify partner, drop from wait pool, drop presence.
    await soft_unpair(ws_id)
    await store.remove_waiting(ws_id)
    await store.unregister_connection(ws_id)

    if ws:
        await ws.safe_close()
    logger.info(f"[{ws_id}] Cleaned up.")


async def websocket_endpoint(websocket: WebSocket):
    # Origin allow-list (cheap rejection before doing any work).
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        logger.warning(f"Rejected WS from disallowed origin: {origin}")
        await websocket.close(code=1008)
        return

    # Rate limit per client IP (sliding window in Redis).
    ip = _client_ip(websocket)
    allowed = await store.check_rate_limit(ip)

    await websocket.accept()

    if not allowed:
        logger.info(f"Rate limited connection from {ip}")
        try:
            await websocket.send_text(json.dumps({
                "name": "RATE_LIMITED",
                "message": "Too many connection attempts. Please wait a minute and try again.",
            }))
        except Exception:
            pass
        await websocket.close(code=1013)  # 1013 = Try Again Later
        return

    # In in-memory mode (REDIS_URL not set), is_ready() always returns
    # True and this block is never reached. It only fires when Redis is
    # configured but the connection was lost at startup.
    if not store.is_ready():
        try:
            await websocket.send_text(json.dumps({
                "name": "SERVER_UNAVAILABLE",
                "message": "Server is temporarily unavailable. Please try again shortly.",
            }))
        except Exception:
            pass
        await websocket.close(code=1011)
        return

    ws_id = str(uuid.uuid4())
    ws = ManagedWebSocket(websocket, ws_id, on_send_fail=lambda _id: asyncio.create_task(cleanup(_id)))
    local_websockets[ws_id] = ws
    await store.register_connection(ws_id)

    logger.info(f"[{ws_id}] Connected from {ip}.")

    try:
        while True:
            try:
                message = await websocket.receive_text()
            except WebSocketDisconnect:
                raise  # handled in outer except
            except Exception as e:
                logger.error(f"[{ws_id}] Receive error: {e}")
                break

            # S1: reject oversized frames (app-level guard alongside --ws-max-size).
            if len(message) > MAX_MESSAGE_BYTES:
                logger.warning(f"[{ws_id}] Message too big ({len(message)} bytes); closing.")
                await websocket.close(code=1009)  # 1009 = Message Too Big
                break

            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"[{ws_id}] Invalid JSON.")
                continue

            # R5: ignore valid-but-non-object JSON (arrays, strings, numbers)
            # instead of crashing the receive loop and dropping the connection.
            if not isinstance(data, dict):
                continue

            msg_name = data.get("name")

            if msg_name == "PAIRING_START":
                # Ensure clean slate (soft_unpair so we don't close current socket).
                await store.remove_waiting(ws_id)
                await soft_unpair(ws_id)

                # Parse topics
                raw_topics = data.get("topics", [])
                if not isinstance(raw_topics, list):
                    raw_topics = []
                if not raw_topics and data.get("topic"):
                    raw_topics = [data.get("topic")]
                normalized_topics = [
                    str(t).strip().lower() for t in raw_topics if str(t).strip()
                ]
                # S2: cap each topic to 50 chars and the list to 3 (server side).
                normalized_topics = [t[:50] for t in normalized_topics][:3]

                await store.enqueue_waiting(ws_id, normalized_topics)
                await store.trigger_wakeup()

            elif msg_name == "PAIRING_ABORT":
                await store.remove_waiting(ws_id)

            elif msg_name == "LEAVE":
                # User manually signalling leave (next button)
                await store.remove_waiting(ws_id)
                await soft_unpair(ws_id)

            # Generic signaling relay (SDP, ICE candidates, etc.)
            # NOTE: chat is now peer-to-peer over the WebRTC data channel and no
            # longer passes through this server.
            # Order matters -> await send
            else:
                # S4: only relay whitelisted WebRTC signaling messages; ignore
                # anything else so arbitrary payloads can't be forwarded to peers.
                if msg_name not in ALLOWED_RELAY:
                    logger.debug(f"[{ws_id}] Ignoring non-relayable message: {msg_name}")
                    continue
                partner_id = await store.get_partner(ws_id)
                if partner_id:
                    await store.route(partner_id, data)

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
    store.set_local_delivery(deliver_local)
    store.set_wakeup_callback(match_event.set)
    await store.connect()

    tasks = [
        asyncio.create_task(store.pubsub_listener()),
        asyncio.create_task(matcher_loop()),
        asyncio.create_task(heartbeat_loop()),
    ]
    yield
    # Shutdown
    logger.info("Server shutting down...")
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    await store.close()


async def ping(request):
    return JSONResponse({
        "message": "Server is awake",
        "instance": store.instance_id(),
        "redis": store.is_ready(),
    })


middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=_cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(
    lifespan=lifespan,
    middleware=middleware,
    routes=[
        Route("/ping", ping),
        WebSocketRoute("/api/matchmaking", websocket_endpoint),
    ]
)
