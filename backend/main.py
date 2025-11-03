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
ready_clients: Set[str] = set()
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
                ready_clients.discard(ws_id)
                partner_id = partners.pop(ws_id, None)
                if partner_id:
                    partners.pop(partner_id, None)

                if not ws.closed:
                    ready_clients.add(ws_id)
                    asyncio.create_task(try_match_partner())

            elif data.get("name") == "PAIRING_ABORT":
                ready_clients.discard(ws_id)

            elif data.get("name") == "LEAVE":
                await cleanup(ws_id)

            elif ws_id in partners:
                partner_id = partners[ws_id]
                partner = websockets.get(partner_id)
                if partner:
                    await partner.send_text(json.dumps(data))

    except WebSocketDisconnect:
        await cleanup(ws_id)


async def try_match_partner():
    async with match_lock:
        while len(ready_clients) >= 2:
            a = ready_clients.pop()
            b = ready_clients.pop()

            ws_a = websockets.get(a)
            ws_b = websockets.get(b)

            if ws_a and not ws_a.closed and ws_b and not ws_b.closed:
                partners[a] = b
                partners[b] = a

                await ws_a.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "GO_FIRST"}))
                await ws_b.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "WAIT"}))
            else:
                # If one is gone, return the other to the pool
                if ws_a and not ws_a.closed:
                    ready_clients.add(a)
                if ws_b and not ws_b.closed:
                    ready_clients.add(b)


async def cleanup(ws_id: str):
    ready_clients.discard(ws_id)

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
