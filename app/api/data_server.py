import asyncio
import logging

import jwt
import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth import ALGORITHM, SECRET_KEY

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Data Server"])


@router.websocket("/api/v1/data-server/ws")
async def data_server_proxy(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Authenticated WebSocket proxy to the CachedDataServer."""
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    from app.config import settings
    ds_url = f"ws://{settings.cached_data_server_host}:{settings.cached_data_server_port}"

    try:
        async with websockets.connect(ds_url) as ds_ws:

            async def client_to_ds():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await ds_ws.send(msg)
                except (WebSocketDisconnect, Exception):
                    pass

            async def ds_to_client():
                try:
                    async for msg in ds_ws:
                        text = msg if isinstance(msg, str) else msg.decode()
                        await websocket.send_text(text)
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_ds()),
                    asyncio.create_task(ds_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.warning("Data server proxy error: %s", e)

    try:
        await websocket.close()
    except Exception:
        pass
