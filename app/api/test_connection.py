import asyncio
import json
import logging
import queue
import sys
import threading
from os.path import dirname, realpath

import jwt
import yaml
from fastapi import APIRouter, Query, WebSocket, status
from fastapi.websockets import WebSocketState

from app.auth import ALGORITHM, SECRET_KEY

sys.path.insert(0, dirname(dirname(dirname(dirname(realpath(__file__))))))

from logger.readers import (  # noqa: E402
    CachedDataReader,
    ComposedReader,
    LogfileReader,
    NetworkReader,
    SerialReader,
    TCPReader,
    TextFileReader,
    TimeoutReader,
    UDPReader,
    SocketReader,
)

router = APIRouter(prefix="/api/v1/ws", tags=["Test Connection"])

_READER_CLASSES: dict = {
    "CachedDataReader": CachedDataReader,
    "ComposedReader": ComposedReader,
    "LogfileReader": LogfileReader,
    "NetworkReader": NetworkReader,
    "SerialReader": SerialReader,
    "TCPReader": TCPReader,
    "TextFileReader": TextFileReader,
    "TimeoutReader": TimeoutReader,
    "UDPReader": UDPReader,
    "SocketReader": SocketReader,
}


def _instantiate_reader(config: dict):
    class_name = config.get("class")
    if not class_name:
        raise ValueError("Reader config must have a 'class' key")
    cls = _READER_CLASSES.get(class_name)
    if cls is None:
        raise ValueError(
            f"Unknown reader class '{class_name}'. "
            f"Supported: {sorted(_READER_CLASSES)}"
        )
    kwargs = config.get("kwargs", {}) or {}
    return cls(**kwargs)


@router.websocket("/test-connection")
async def websocket_test_connection(
    websocket: WebSocket,
    token: str = Query(...),
):
    """WebSocket endpoint for live-streaming records from a reader.

    Protocol:
      Client → {"action": "start", "config_yaml": "<yaml string>"}
      Server → {"type": "status",  "message": "started"}
      Server → {"type": "record",  "data": "<string>"}
      Server → {"type": "error",   "message": "<string>"}
      Client → {"action": "stop"}
      Server → {"type": "status",  "message": "stopped"}
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub") or payload.get("type") == "refresh":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except jwt.PyJWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    stop_event = threading.Event()
    record_queue: queue.Queue = queue.Queue()

    def reader_loop(reader):
        try:
            while not stop_event.is_set():
                record = reader.read()
                if record is not None:
                    record_queue.put({"type": "record", "data": str(record)})
        except Exception as e:
            record_queue.put({"type": "error", "message": str(e)})

    try:
        # Wait for a start command
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
        except asyncio.TimeoutError:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(
                    {"type": "error", "message": "Timed out waiting for start command"}
                )
            return

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "message": "Invalid JSON"})
            return

        if msg.get("action") != "start":
            await websocket.send_json(
                {"type": "error", "message": "Expected action 'start'"}
            )
            return

        config_yaml = msg.get("config_yaml", "")
        try:
            config = yaml.safe_load(config_yaml)
            reader = _instantiate_reader(config)
        except Exception as e:
            await websocket.send_json(
                {"type": "error", "message": f"Failed to create reader: {e}"}
            )
            return

        await websocket.send_json({"type": "status", "message": "started"})

        reader_thread = threading.Thread(target=reader_loop, args=(reader,), daemon=True)
        reader_thread.start()

        # Pump records to the client while listening for stop
        while websocket.client_state == WebSocketState.CONNECTED:
            # Drain any queued records
            while True:
                try:
                    item = record_queue.get_nowait()
                    await websocket.send_json(item)
                except queue.Empty:
                    break

            # Check for an incoming stop message (non-blocking)
            try:
                raw2 = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                msg2 = json.loads(raw2)
                if msg2.get("action") == "stop":
                    break
            except (asyncio.TimeoutError, json.JSONDecodeError):
                pass
            except Exception:
                break

    finally:
        stop_event.set()
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json({"type": "status", "message": "stopped"})
                await websocket.close()
            except Exception:
                pass
        logging.debug("test-connection WebSocket closed")
