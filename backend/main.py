# app/main.py
import json
import uuid
from typing import Dict, Set
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from starlette.routing import Route
import asyncio

websockets: Dict[str, "ManagedWebSocket"] = {}
partners: Dict[str, str] = {}
ready_clients: Dict[str, list] = {}
match_lock = asyncio.Lock()

async def ping(request):
    return JSONResponse({"message": "Server is awake"})
class ManagedWebSocket:
    def __init__(self, websocket: WebSocket, ws_id: str):
        self.websocket = websocket
        self.id = ws_id
        self.closed = False

    async def safe_close(self):
        if not self.closed:
            await self.websocket.close()
            self.closed = True

    async def send_text(self, message: str):
        if not self.closed:
            try:
                await self.websocket.send_text(message)
            except:
                self.closed = True


async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_id = str(uuid.uuid4())
    ws = ManagedWebSocket(websocket, ws_id)
    websockets[ws_id] = ws

    try:
        while True:
            try:
                data = json.loads(await websocket.receive_text())
            except:
                break

            if data.get("name") == "PAIRING_START":
                # Clean up any existing state
                if ws_id in ready_clients:
                     del ready_clients[ws_id]
                     
                partner_id = partners.pop(ws_id, None)
                if partner_id:
                    partners.pop(partner_id, None)

                if not ws.closed:
                    # Support both new 'topics' (list) and old 'topic' (str)
                    raw_topics = data.get("topics", [])
                    if not raw_topics and data.get("topic"):
                        raw_topics = [data.get("topic")]
                        
                    # Normalize: lowercase, strip
                    topics = [str(t).strip().lower() for t in raw_topics if str(t).strip()]
                    
                    ready_clients[ws_id] = topics
                    asyncio.create_task(try_match_partner())

            elif data.get("name") == "PAIRING_ABORT":
                if ws_id in ready_clients:
                    del ready_clients[ws_id]

            elif data.get("name") == "LEAVE":
                await cleanup(ws_id)
            
            elif data.get("name") == "CHAT":
                # Relay chat message to partner
                partner_id = partners.get(ws_id)
                if partner_id:
                    partner = websockets.get(partner_id)
                    if partner:
                         await partner.send_text(json.dumps(data))

            elif ws_id in partners:
                partner_id = partners[ws_id]
                partner = websockets.get(partner_id)
                if partner:
                    await partner.send_text(json.dumps(data))

    except WebSocketDisconnect:
        await cleanup(ws_id)


async def try_match_partner():
    async with match_lock:
        if len(ready_clients) < 2:
            return

        while len(ready_clients) >= 2:
            client_ids = list(ready_clients.keys())
            if not client_ids:
                break
                
            candidate_a_id = client_ids[0]
            topics_a = set(ready_clients[candidate_a_id])
            
            best_match_id = None
            
            # Prefer overlap
            if topics_a:
                for other_id in client_ids[1:]:
                    topics_b = set(ready_clients[other_id])
                    if not topics_a.isdisjoint(topics_b):
                        best_match_id = other_id
                        break
            
            # Fallback: pick next available
            if not best_match_id:
                best_match_id = client_ids[1]
            
            # Store topics for re-queueing in case of failure (simplified safe retrieval)
            saved_topics_a = ready_clients[candidate_a_id]
            saved_topics_b = ready_clients[best_match_id]

            del ready_clients[candidate_a_id]
            del ready_clients[best_match_id]
            
            ws_a = websockets.get(candidate_a_id)
            ws_b = websockets.get(best_match_id)

            if ws_a and not ws_a.closed and ws_b and not ws_b.closed:
                partners[candidate_a_id] = best_match_id
                partners[best_match_id] = candidate_a_id

                await ws_a.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "GO_FIRST"}))
                await ws_b.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "WAIT"}))
            else:
                # If matching failed (someone disconnected), return survivor to pool
                if ws_a and not ws_a.closed:
                    ready_clients[candidate_a_id] = saved_topics_a
                if ws_b and not ws_b.closed:
                    ready_clients[best_match_id] = saved_topics_b


async def cleanup(ws_id: str):
    if ws_id in ready_clients:
        del ready_clients[ws_id]

    ws = websockets.pop(ws_id, None)
    if not ws:
        return

    partner_id = partners.pop(ws_id, None)
    if partner_id:
        partners.pop(partner_id, None)
        partner = websockets.get(partner_id)
        if partner:
            await partner.send_text(json.dumps({"name": "PARTNER_LEFT"}))

    await ws.safe_close()


app = Starlette(
    routes=[
        Route("/ping", ping),
        WebSocketRoute("/api/matchmaking", websocket_endpoint),
    ]
)
