import asyncio
import glob
import json
import socket
import threading
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.db import config_crud as crud_configs, logger_crud as crud_loggers
from app.deps import get_async_server_api, get_async_session
from async_fastapi_server_api import AsyncFastAPIServerAPI

router = APIRouter(prefix="/api/v1/connection", tags=["Connection"])

_MAX_DURATION = 30
_MAX_MESSAGES = 20
_PORT_RELEASE_WAIT = 3  # seconds to wait after setting a logger to off


# ---------------------------------------------------------------------------
# Port-in-config detection
# ---------------------------------------------------------------------------

def _config_uses_serial(obj: Any, port: str) -> bool:
    if isinstance(obj, dict):
        cls = obj.get("class", "")
        kwargs = obj.get("kwargs", {}) if isinstance(obj.get("kwargs"), dict) else {}
        if "Serial" in cls and kwargs.get("port") == port:
            return True
        return any(_config_uses_serial(v, port) for v in obj.values())
    if isinstance(obj, list):
        return any(_config_uses_serial(item, port) for item in obj)
    return False


def _config_uses_udp(obj: Any, port: int) -> bool:
    if isinstance(obj, dict):
        cls = obj.get("class", "")
        kwargs = obj.get("kwargs", {}) if isinstance(obj.get("kwargs"), dict) else {}
        if "UDP" in cls:
            port_val = kwargs.get("port")
            if port_val is not None:
                try:
                    if int(port_val) == port:
                        return True
                except (TypeError, ValueError):
                    pass
        return any(_config_uses_udp(v, port) for v in obj.values())
    if isinstance(obj, list):
        return any(_config_uses_udp(item, port) for item in obj)
    return False


def _config_json_uses_port(config_json: str, *, serial_port: str | None, udp_port: int | None) -> bool:
    try:
        cfg = json.loads(config_json)
    except (json.JSONDecodeError, TypeError):
        return False
    if serial_port:
        return _config_uses_serial(cfg, serial_port)
    if udp_port is not None:
        return _config_uses_udp(cfg, udp_port)
    return False


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# Streaming readers
# ---------------------------------------------------------------------------

async def _stream_serial(port: str, baud_rate: int, duration: int) -> AsyncGenerator[str, None]:
    try:
        import serial
    except ImportError:
        yield _sse({"type": "error", "message": "pyserial is not installed"})
        return

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _read() -> None:
        try:
            deadline = time.monotonic() + duration
            count = 0
            with serial.Serial(port=port, baudrate=baud_rate, timeout=1.0) as ser:
                while time.monotonic() < deadline and count < _MAX_MESSAGES:
                    line = ser.readline()
                    if line:
                        msg = line.decode("utf-8", errors="replace").rstrip()
                        loop.call_soon_threadsafe(queue.put_nowait, msg)
                        count += 1
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, f"\x00ERROR\x00{e}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_read, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, str) and item.startswith("\x00ERROR\x00"):
            yield _sse({"type": "error", "message": item[8:]})
            return
        yield _sse({"type": "message", "data": item})


async def _stream_udp(host: str, port: int, duration: int) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _read() -> None:
        try:
            deadline = time.monotonic() + duration
            count = 0
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
                sock.settimeout(1.0)
                while time.monotonic() < deadline and count < _MAX_MESSAGES:
                    try:
                        data, _ = sock.recvfrom(65535)
                        msg = data.decode("utf-8", errors="replace").rstrip()
                        loop.call_soon_threadsafe(queue.put_nowait, msg)
                        count += 1
                    except (socket.timeout, TimeoutError):
                        pass
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, f"\x00ERROR\x00{e}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_read, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, str) and item.startswith("\x00ERROR\x00"):
            yield _sse({"type": "error", "message": item[8:]})
            return
        yield _sse({"type": "message", "data": item})


async def _stream_cds(key: str, url: str, duration: int) -> AsyncGenerator[str, None]:
    import websockets

    ws_url = url if url.startswith("ws://") or url.startswith("wss://") else f"ws://{url}"
    subscription = json.dumps({"type": "subscribe", "fields": {key: {"seconds": 0}}})
    deadline = asyncio.get_event_loop().time() + duration
    count = 0

    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(subscription)
            while asyncio.get_event_loop().time() < deadline and count < _MAX_MESSAGES:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                    msg = json.dumps(data, indent=2) if isinstance(data, dict) else str(raw)
                    yield _sse({"type": "message", "data": msg})
                    count += 1
                except (asyncio.TimeoutError, TimeoutError):
                    pass
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/serial-ports",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def list_serial_ports() -> dict[str, Any]:
    """Return tty device paths found under /dev, sorted."""
    ports = sorted(glob.glob("/dev/tty*"))
    return {"ports": ports}


@router.get(
    "/cds-fields",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def list_cds_fields(cds_url: str = "localhost:8766") -> dict[str, Any]:
    """Connect to a CachedDataServer and return its list of available field names."""
    import websockets

    ws_url = cds_url if cds_url.startswith("ws://") or cds_url.startswith("wss://") else f"ws://{cds_url}"
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "fields"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(raw)
            fields = sorted(data.get("fields", []))
            return {"fields": fields}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach CDS at {cds_url}: {e}")


@router.get(
    "/check-port",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def check_port(
    conn_type: str,
    port: str | None = None,
    udp_port: int | None = None,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Check whether any active logger config is bound to the given port."""
    if conn_type == "serial" and not port:
        raise HTTPException(status_code=400, detail="port required for serial check")
    if conn_type == "udp" and udp_port is None:
        raise HTTPException(status_code=400, detail="udp_port required for udp check")

    loggers = await crud_loggers.list_loggers(session)
    configs = await crud_configs.list_configs(session)
    config_map = {c["id"]: c for c in configs}

    for logger in loggers:
        active_config_id = logger.get("active_config")
        if not active_config_id:
            continue
        config = config_map.get(active_config_id)
        if not config or not config.get("config_json"):
            continue

        uses_port = _config_json_uses_port(
            config["config_json"],
            serial_port=port if conn_type == "serial" else None,
            udp_port=udp_port if conn_type == "udp" else None,
        )
        if not uses_port:
            continue

        logger_configs = [c for c in configs if c.get("logger_id") == logger["id"]]
        off_config = next(
            (c for c in logger_configs if c["id"].endswith("->off")),
            None,
        )

        return {
            "in_use": True,
            "logger_id": logger["id"],
            "active_config_id": active_config_id,
            "off_config_id": off_config["id"] if off_config else None,
        }

    return {"in_use": False, "logger_id": None, "active_config_id": None, "off_config_id": None}


@router.post(
    "/stream",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def stream_connection(
    conn_type: str,
    duration: int = 5,
    port: str | None = None,
    baud_rate: int = 9600,
    host: str = "",
    udp_port: int | None = None,
    cds_key: str | None = None,
    cds_url: str = "localhost:8766",
    logger_to_pause: str | None = None,
    off_config_id: str | None = None,
    restore_config_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api),
) -> StreamingResponse:
    """Stream connection data as Server-Sent Events."""
    duration = min(max(duration, 1), _MAX_DURATION)

    async def generate() -> AsyncGenerator[str, None]:
        paused = False
        try:
            if logger_to_pause and off_config_id:
                await server_api.set_active_logger_config(logger_to_pause, off_config_id)
                paused = True
                await asyncio.sleep(_PORT_RELEASE_WAIT)

            if conn_type == "serial":
                if not port:
                    yield _sse({"type": "error", "message": "port is required"})
                    return
                async for event in _stream_serial(port, baud_rate, duration):
                    yield event

            elif conn_type == "udp":
                if udp_port is None:
                    yield _sse({"type": "error", "message": "udp_port is required"})
                    return
                async for event in _stream_udp(host or "0.0.0.0", udp_port, duration):
                    yield event

            elif conn_type == "cds":
                if not cds_key:
                    yield _sse({"type": "error", "message": "cds_key is required"})
                    return
                async for event in _stream_cds(cds_key, cds_url, duration):
                    yield event

            else:
                yield _sse({"type": "error", "message": f"Unknown connection type: {conn_type}"})
                return

            yield _sse({"type": "done"})

        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
        finally:
            if paused and restore_config_id and logger_to_pause:
                try:
                    await server_api.set_active_logger_config(logger_to_pause, restore_config_id)
                except Exception:
                    pass

    return StreamingResponse(generate(), media_type="text/event-stream")
