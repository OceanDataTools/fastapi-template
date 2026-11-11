import asyncio
import json

import websockets
from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketState

from app.auth import accepts_apikey, authenticate_websocket
from app.config import settings

router = APIRouter(prefix="/api/v1/ws", tags=["Data Server"])

DATA_SERVER_ROUTE = "/api/v1/ws/data-server"

# Reply sent instead of forwarding a client 'publish' to the CDS. Loggers
# publish to the CachedDataServer directly on localhost; clients reaching it
# through this proxy are on other machines and only read.
_PUBLISH_FORBIDDEN = json.dumps(
    {
        "type": "publish",
        "status": 403,
        "message": "Publishing to the CachedDataServer is not permitted "
        "through this proxy",
    }
)


def _is_publish(message: str) -> bool:
    try:
        request = json.loads(message)
    except ValueError:
        return False
    return isinstance(request, dict) and request.get("type") == "publish"


@router.websocket("/data-server")
@accepts_apikey
async def websocket_data_server_proxy(websocket: WebSocket):
    """Authenticated, read-only WebSocket proxy to the CachedDataServer.

    Accepts either a JWT access token or an API key with the WEBSOCKET
    permission on this route:

      ws://<host>/api/v1/ws/data-server?token=<jwt>
      ws://<host>/api/v1/ws/data-server?api_key=<key>   (or X-API-Key header)

    Once authenticated, JSON messages are forwarded in both directions,
    preserving the CachedDataServer subscribe/ready/data protocol, except
    that 'publish' requests are answered with status 403 and not forwarded.
    """
    if (
        await authenticate_websocket(websocket, DATA_SERVER_ROUTE, allow_apikey=True)
        is None
    ):
        return

    await websocket.accept()

    cds_url = (
        f"ws://{settings.cached_data_server_host}:{settings.cached_data_server_port}"
    )

    try:
        async with websockets.connect(cds_url) as cds_ws:

            async def client_to_cds():
                try:
                    while True:
                        data = await websocket.receive_text()
                        if _is_publish(data):
                            await websocket.send_text(_PUBLISH_FORBIDDEN)
                            continue
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
