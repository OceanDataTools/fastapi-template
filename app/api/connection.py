import asyncio
import glob
import json
import socket
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
    """Check whether any active logger config is bound to the given port.

    Returns conflict info so the frontend can warn the user before testing.
    """
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

        # Found a conflict — locate the off config for this logger
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


# ---------------------------------------------------------------------------
# Connection readers (blocking, run in a thread)
# ---------------------------------------------------------------------------

def _read_serial(port: str, baud_rate: int, duration: int) -> list[str]:
    try:
        import serial
    except ImportError:
        raise RuntimeError("pyserial is not installed")

    messages: list[str] = []
    deadline = time.monotonic() + duration
    with serial.Serial(port=port, baudrate=baud_rate, timeout=1.0) as ser:
        while time.monotonic() < deadline and len(messages) < _MAX_MESSAGES:
            line = ser.readline()
            if line:
                messages.append(line.decode("utf-8", errors="replace").rstrip())
    return messages


def _read_udp(host: str, port: int, duration: int) -> list[str]:
    messages: list[str] = []
    deadline = time.monotonic() + duration
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(1.0)
        while time.monotonic() < deadline and len(messages) < _MAX_MESSAGES:
            try:
                data, _ = sock.recvfrom(65535)
                messages.append(data.decode("utf-8", errors="replace").rstrip())
            except (socket.timeout, TimeoutError):
                pass
    return messages


async def _read_cds(key: str, url: str, duration: int) -> list[str]:
    import websockets

    ws_url = url if url.startswith("ws://") or url.startswith("wss://") else f"ws://{url}"
    subscription = json.dumps({"type": "subscribe", "fields": {key: {"seconds": 0}}})
    messages: list[str] = []
    deadline = asyncio.get_event_loop().time() + duration

    async with websockets.connect(ws_url) as ws:
        await ws.send(subscription)
        while asyncio.get_event_loop().time() < deadline and len(messages) < _MAX_MESSAGES:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                messages.append(json.dumps(data, indent=2) if isinstance(data, dict) else str(raw))
            except (asyncio.TimeoutError, TimeoutError):
                pass

    return messages


@router.post(
    "/test",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def test_connection(
    conn_type: str,
    duration: int = 5,
    # serial params
    port: str | None = None,
    baud_rate: int = 9600,
    # udp params
    host: str = "",
    udp_port: int | None = None,
    # cds params
    cds_key: str | None = None,
    cds_url: str = "localhost:8766",
    # optional logger pause/restore
    logger_to_pause: str | None = None,
    off_config_id: str | None = None,
    restore_config_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api),
) -> dict[str, Any]:
    duration = min(max(duration, 1), _MAX_DURATION)

    paused = False
    try:
        if logger_to_pause and off_config_id:
            await server_api.set_active_logger_config(logger_to_pause, off_config_id)
            paused = True
            await asyncio.sleep(_PORT_RELEASE_WAIT)

        if conn_type == "serial":
            if not port:
                raise HTTPException(status_code=400, detail="port is required for serial connections")
            messages = await asyncio.to_thread(_read_serial, port, baud_rate, duration)

        elif conn_type == "udp":
            if udp_port is None:
                raise HTTPException(status_code=400, detail="udp_port is required for UDP connections")
            messages = await asyncio.to_thread(_read_udp, host or "0.0.0.0", udp_port, duration)

        elif conn_type == "cds":
            if not cds_key:
                raise HTTPException(status_code=400, detail="cds_key is required for CDS connections")
            messages = await _read_cds(cds_key, cds_url, duration)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown connection type: {conn_type}")

    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "messages": [], "error": str(e)}
    finally:
        if paused and restore_config_id and logger_to_pause:
            try:
                await server_api.set_active_logger_config(logger_to_pause, restore_config_id)
            except Exception:
                pass

    return {"success": True, "messages": messages, "error": None}
