# app/main.py
import os
import json
from typing import Set, Dict
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.websockets import WebSocket, WebSocketDisconnect


clients: Set[WebSocket] = set()
partners: Dict[WebSocket, WebSocket] = {}
ready_clients: Set[WebSocket] = set()

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
            await self.websocket.send_text(message)

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)

    try:
        while True:
            data = json.loads(await websocket.receive_text())

            if data.get("name") == "PAIRING_START":
                ready_clients.add(websocket)
                await try_match_partner()

            elif data.get("name") == "PAIRING_ABORT":
                ready_clients.discard(websocket)

            elif data.get("name") == "LEAVE":
                await cleanup(websocket)

            elif websocket in partners:
                partner = partners[websocket]
                try:
                    await partner.send_text(json.dumps(data))
                except:
                    await cleanup(partner)

    except WebSocketDisconnect:
        await cleanup(websocket)

async def try_match_partner():
    if len(ready_clients) >= 2:
        a = ready_clients.pop()
        b = ready_clients.pop()

        partners[a] = b
        partners[b] = a

        await a.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "GO_FIRST"}))
        await b.send_text(json.dumps({"name": "PARTNER_FOUND", "data": "WAIT"}))

async def cleanup(ws: WebSocket):
    clients.discard(ws)
    ready_clients.discard(ws)

    if ws in partners:
        partner = partners.pop(ws)
        partners.pop(partner, None)
        ready_clients.discard(partner)

        await partner.send_text(json.dumps({"name": "PARTNER_LEFT"}))
        

async def homepage(_):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

app = Starlette(
    routes=[
        WebSocketRoute("/api/matchmaking", websocket_endpoint),
    ]
)
