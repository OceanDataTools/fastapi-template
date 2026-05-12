import asyncio

import jwt
import websockets
from fastapi import APIRouter, Query, WebSocket, status
from fastapi.websockets import WebSocketState

from app.auth import ALGORITHM, SECRET_KEY
from app.config import settings

router = APIRouter(prefix="/api/v1/ws", tags=["Data Server"])


@router.websocket("/data-server")
async def websocket_data_server_proxy(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Authenticated WebSocket proxy to the CachedDataServer.

    Browsers cannot set custom headers on WebSocket connections, so the JWT
    is passed as a query parameter: ws://<host>/api/v1/ws/data-server?token=<jwt>

    Once authenticated, all JSON messages are forwarded transparently in both
    directions, preserving the full CachedDataServer subscribe/ready/data protocol.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except jwt.PyJWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    cds_url = f"ws://{settings.cached_data_server_host}:{settings.cached_data_server_port}"

    try:
        async with websockets.connect(cds_url) as cds_ws:

            async def client_to_cds():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await cds_ws.send(data)
                except Exception:
                    pass

            async def cds_to_client():
                try:
                    async for message in cds_ws:
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_text(message)
                        else:
                            break
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_cds()),
                    asyncio.create_task(cds_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except OSError:
        # CachedDataServer not reachable
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(
                '{"type":"error","status":503,"message":"CachedDataServer unavailable"}'
            )
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
