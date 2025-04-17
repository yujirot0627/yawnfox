# app/main.py
import os
import json
from typing import Set, Dict
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.websockets import WebSocket, WebSocketDisconnect


class ManagedWebSocket:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
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

clients: Set[ManagedWebSocket] = set()
partners: Dict[ManagedWebSocket, ManagedWebSocket] = {}
ready_clients: Set[ManagedWebSocket] = set()

async def websocket_endpoint(websocket: WebSocket):
    ws = ManagedWebSocket(websocket)
    await websocket.accept()
    clients.add(ws)

    try:
        while True:
            try:
                data = json.loads(await websocket.receive_text())
            except:
                break 

            if data.get("name") == "PAIRING_START":
                ready_clients.add(ws)
                await try_match_partner()

            elif data.get("name") == "PAIRING_ABORT":
                ready_clients.discard(ws)

            elif data.get("name") == "LEAVE":
                await cleanup(ws)

            elif ws in partners:
                partner = partners[ws]
                await partner.send_text(json.dumps(data))

    except WebSocketDisconnect:
        await cleanup(ws)

async def try_match_partner():
    ready = [ws for ws in ready_clients if not ws.closed]

    if len(ready_clients) >= 2:
        a = ready.pop()
        b = ready.pop()

        ready_clients.discard(a)
        ready_clients.discard(b)

        partners[a] = b
        partners[b] = a

        await a.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "GO_FIRST"}))
        await b.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "WAIT"}))

async def cleanup(ws: ManagedWebSocket):
    clients.discard(ws)
    ready_clients.discard(ws)

    if ws in partners:
        partner = partners.pop(ws)
        partners.pop(partner, None)
        ready_clients.discard(partner)

        await partner.send_text(json.dumps({"name": "PARTNER_LEFT"}))

    await ws.safe_close()
        

async def homepage(_):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

app = Starlette(
    routes=[
        WebSocketRoute("/api/matchmaking", websocket_endpoint),
    ]
)
