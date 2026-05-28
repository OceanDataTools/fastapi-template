import asyncio
import json
import logging
import re

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models_openrvdas import LastUpdate

# "2026-05-05 12:34:56,789Z 20 INFO logger_manager.py:360 some message"
_LOG_RE = re.compile(r"^(\S+Z)\s+(\d+)\s+(\w+)\s+(\S+)\s+(.*)$", re.DOTALL)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Updates"])

_READY = json.dumps({"type": "ready"})
# If no CDS data arrives for this long, reconnect and re-subscribe so a
# quiet CDS (e.g. logger_manager briefly offline) never blocks forever.
# Chosen to be comfortably longer than the websockets default ping interval
# (20 s) so routine keepalive pings don't trigger a reconnect.
_CDS_RECV_TIMEOUT = 60.0


def _cds_url() -> str:
    return f"ws://{settings.cached_data_server_host}:{settings.cached_data_server_port}"


async def _db_poll_loop(websocket: WebSocket) -> None:
    """Poll LastUpdate table; push change events to the client."""
    last_ts = None

    while True:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(LastUpdate).order_by(LastUpdate.timestamp.desc()).limit(1)
            )
            latest = result.scalar_one_or_none()
            ts = latest.timestamp if latest else None

        if last_ts is None:
            last_ts = ts
            await websocket.send_json({"type": "update"})
        elif ts != last_ts:
            last_ts = ts
            await websocket.send_json({"type": "update"})

        await asyncio.sleep(0.5)


async def _cds_status_loop(websocket: WebSocket) -> None:
    """Subscribe to status:logger_status in the CDS and forward to the client.

    Also owns CDS connectivity reporting: sends {"type": "status",
    "cds_connected": bool} whenever the connection state changes, so
    _db_poll_loop no longer needs to probe CDS independently.

    Retries on CDS failures with exponential backoff.  Reconnects after a
    recv timeout so a quiet CDS (e.g. logger_manager briefly offline) never
    causes the subscription to block indefinitely.  Exits immediately when
    the client WebSocket is no longer writable.
    """
    retry_delay = 1.0
    last_cds: bool | None = None

    async def _notify(connected: bool) -> None:
        nonlocal last_cds
        if connected != last_cds:
            last_cds = connected
            try:
                await websocket.send_json(
                    {"type": "status", "cds_connected": connected}
                )
            except Exception:
                pass

    while True:
        try:
            async with websockets.connect(_cds_url()) as cds_ws:
                retry_delay = 1.0
                await _notify(True)
                await cds_ws.send(
                    json.dumps(
                        {
                            "type": "subscribe",
                            "fields": {"status:logger_status": {"seconds": -1}},
                        }
                    )
                )

                while True:
                    try:
                        raw = await asyncio.wait_for(
                            cds_ws.recv(), timeout=_CDS_RECV_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        break  # Exit inner loop → outer loop reconnects immediately

                    msg = json.loads(raw if isinstance(raw, str) else raw.decode())

                    if msg.get("type") == "subscribe" and msg.get("status") == 200:
                        await cds_ws.send(_READY)

                    elif msg.get("type") == "data":
                        pairs = (msg.get("data") or {}).get("status:logger_status")
                        if pairs:
                            value = pairs[-1][1]
                            statuses = {
                                lid: {
                                    "status": info["status"],
                                    "config": info.get("config"),
                                }
                                for lid, info in value.items()
                                if isinstance(info, dict) and "status" in info
                            }
                            if statuses:
                                try:
                                    await websocket.send_json(
                                        {
                                            "type": "logger_status",
                                            "data": statuses,
                                        }
                                    )
                                except Exception:
                                    return  # Client disconnected
                        await cds_ws.send(_READY)

        except Exception as e:
            await _notify(False)
            logger.debug(
                "CDS status loop: %s: %s, retrying in %.1fs",
                type(e).__name__,
                e,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


def _parse_log_entry(source: str, cds_ts: float, value: object) -> dict | None:
    """Parse a CDS log value into a structured log entry dict."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None

    # JSON format produced by StdErrLoggingHandler(parse_to_json=True)
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict) and "message" in parsed:
            return {
                "source": source,
                "timestamp": cds_ts,
                "levelname": parsed.get("levelname", "INFO"),
                "levelno": int(parsed.get("levelno", 20)),
                "message": parsed.get("message", ""),
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Raw format: "<datetime>Z <levelno> <levelname> <file>:<line> <message>"
    m = _LOG_RE.match(value)
    if m:
        _asctime, levelno_str, levelname, location, message = m.groups()
        try:
            levelno = int(levelno_str)
        except ValueError:
            levelno = 20
        return {
            "source": source,
            "timestamp": cds_ts,
            "levelname": levelname,
            "levelno": levelno,
            "message": f"{location} {message}",
        }

    return {
        "source": source,
        "timestamp": cds_ts,
        "levelname": "INFO",
        "levelno": 20,
        "message": value,
    }


_LOG_HISTORY_RECORDS = 100  # Records per logger to fetch on first connect


async def _cds_log_loop(websocket: WebSocket) -> None:
    """Subscribe to stderr fields in the CDS and forward log entries to the client.

    Uses CDS wildcard subscriptions (stderr:logger:*) so every logger field is
    covered regardless of whether its name matches the DB.  Reconnects on
    timeout so the wildcard is re-evaluated after a config change adds new
    logger fields to the CDS cache.

    On the first connect a lookback window is used so recent log history is
    sent immediately (restoring the log panel and warning indicators after a
    page refresh).  Subsequent reconnects use seconds=0 to avoid re-sending
    already-delivered messages.
    """
    retry_delay = 1.0
    first_connect = True

    while True:
        try:
            if first_connect:
                # seconds=1 is required — seconds=0 causes the CDS to skip the
                # back_records logic entirely via an early continue.  seconds=1
                # makes every existing record "older than 1 second", so the CDS
                # sets the lookback boundary just before the Nth-from-last record
                # and returns exactly back_records records per field.
                history = {"seconds": 1, "back_records": _LOG_HISTORY_RECORDS}
            else:
                history = {"seconds": 0}
            fields: dict = {
                "stderr:logger_manager": history,
                "stderr:logger:*": history,
            }

            async with websockets.connect(_cds_url()) as cds_ws:
                retry_delay = 1.0
                first_connect = False
                await cds_ws.send(json.dumps({"type": "subscribe", "fields": fields}))

                while True:
                    try:
                        raw = await asyncio.wait_for(
                            cds_ws.recv(), timeout=_CDS_RECV_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        break  # Reconnect to refresh logger list

                    msg = json.loads(raw if isinstance(raw, str) else raw.decode())

                    if msg.get("type") == "subscribe" and msg.get("status") == 200:
                        await cds_ws.send(_READY)

                    elif msg.get("type") == "data":
                        data = msg.get("data") or {}
                        entries = []

                        for field_name, pairs in data.items():
                            if not field_name.startswith("stderr:") or not isinstance(
                                pairs, list
                            ):
                                continue
                            if field_name == "stderr:logger_manager":
                                source = "logger_manager"
                            elif field_name.startswith("stderr:logger:"):
                                source = field_name[len("stderr:logger:") :]
                            else:
                                continue

                            for pair in pairs:
                                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                                    continue
                                entry = _parse_log_entry(source, pair[0], pair[1])
                                if entry:
                                    entries.append(entry)

                        if entries:
                            entries.sort(key=lambda e: e["timestamp"])
                            try:
                                await websocket.send_json(
                                    {
                                        "type": "log_entries",
                                        "data": entries,
                                    }
                                )
                            except Exception:
                                return  # Client disconnected

                        await cds_ws.send(_READY)

        except Exception as e:
            logger.debug(
                "CDS log loop: %s: %s, retrying in %.1fs",
                type(e).__name__,
                e,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


@router.websocket("/api/v1/updates/ws")
async def logger_state_updates(websocket: WebSocket):
    """Push state-change notifications, CDS health, live logger status, and log entries."""
    await websocket.accept()

    db_task = asyncio.create_task(_db_poll_loop(websocket))
    cds_task = asyncio.create_task(_cds_status_loop(websocket))
    log_task = asyncio.create_task(_cds_log_loop(websocket))

    try:
        await asyncio.wait(
            [db_task, cds_task, log_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        db_task.cancel()
        cds_task.cancel()
        log_task.cancel()
        await asyncio.gather(db_task, cds_task, log_task, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
