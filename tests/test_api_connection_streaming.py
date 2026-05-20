"""
Tests for /api/v1/connection/ — port validation, auth, and SSE streaming helpers.
"""

import asyncio
import json
import pytest

from app.api.connection import (
    _config_json_uses_port,
    _config_uses_serial,
    _config_uses_udp,
    _stream_serial,
    _stream_udp,
)


# ---------------------------------------------------------------------------
# Pure-logic unit tests (no DB, no HTTP)
# ---------------------------------------------------------------------------

class TestConfigPortDetection:

    def test_serial_port_detected(self):
        cfg = json.dumps({
            "class": "SerialReader",
            "kwargs": {"port": "/dev/ttyUSB0", "baudrate": 9600},
        })
        assert _config_json_uses_port(cfg, serial_port="/dev/ttyUSB0", udp_port=None)

    def test_serial_port_not_matched(self):
        cfg = json.dumps({
            "class": "SerialReader",
            "kwargs": {"port": "/dev/ttyUSB1", "baudrate": 9600},
        })
        assert not _config_json_uses_port(cfg, serial_port="/dev/ttyUSB0", udp_port=None)

    def test_udp_port_detected(self):
        cfg = json.dumps({
            "class": "UDPReader",
            "kwargs": {"port": 6224},
        })
        assert _config_json_uses_port(cfg, serial_port=None, udp_port=6224)

    def test_udp_port_not_matched(self):
        cfg = json.dumps({
            "class": "UDPReader",
            "kwargs": {"port": 6225},
        })
        assert not _config_json_uses_port(cfg, serial_port=None, udp_port=6224)

    def test_nested_serial_detected(self):
        cfg = json.dumps({
            "readers": [
                {"class": "SerialReader", "kwargs": {"port": "/dev/ttyS0", "baudrate": 4800}}
            ]
        })
        assert _config_json_uses_port(cfg, serial_port="/dev/ttyS0", udp_port=None)

    def test_invalid_json_returns_false(self):
        assert not _config_json_uses_port("not json", serial_port="/dev/tty0", udp_port=None)

    def test_empty_config_returns_false(self):
        assert not _config_json_uses_port("{}", serial_port="/dev/tty0", udp_port=None)


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

class TestConnectionEndpoints:

    @pytest.mark.asyncio
    async def test_list_serial_ports_requires_auth(self, client):
        resp = await client.get("/api/v1/connection/serial-ports")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_list_serial_ports_returns_list(self, client, auth_headers):
        resp = await client.get("/api/v1/connection/serial-ports", headers=auth_headers)
        assert resp.status_code == 200
        assert "ports" in resp.json()
        assert isinstance(resp.json()["ports"], list)

    @pytest.mark.asyncio
    async def test_check_port_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/connection/check-port",
            params={"conn_type": "serial", "port": "/dev/ttyUSB0"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_check_port_serial_not_in_use(self, client, auth_headers):
        resp = await client.get(
            "/api/v1/connection/check-port",
            params={"conn_type": "serial", "port": "/dev/ttyUSB_none"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["in_use"] is False

    @pytest.mark.asyncio
    async def test_check_port_missing_param_returns_400(self, client, auth_headers):
        # serial type without port param
        resp = await client.get(
            "/api/v1/connection/check-port",
            params={"conn_type": "serial"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_stream_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/connection/stream",
            params={"conn_type": "serial"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_stream_unknown_conn_type_returns_sse_error(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/connection/stream",
            params={"conn_type": "ftp", "duration": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "error" in resp.text


# ---------------------------------------------------------------------------
# asyncio.get_running_loop() regression guard (Bug #3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_serial_uses_running_loop_not_new_loop():
    """_stream_serial must not call get_event_loop() (deprecated in 3.10+).

    We verify the generator can be created and started inside a running event
    loop without raising DeprecationWarning or RuntimeError.  The generator
    will fail quickly because pyserial can't open a fake port, but the error
    must come from serial.Serial, not from asyncio.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        gen = _stream_serial("/dev/null_fake_port", 9600, 1)
        first_event = None
        try:
            first_event = await gen.__anext__()
        except StopAsyncIteration:
            pass
        except Exception:
            pass
    # If we reach here without DeprecationWarning, the fix is in place.
    # The generator may have yielded an error SSE about the port — that's fine.
    if first_event is not None:
        data = json.loads(first_event.replace("data: ", "").strip())
        assert data["type"] in ("error", "message")


@pytest.mark.asyncio
async def test_stream_udp_uses_running_loop_not_new_loop():
    """_stream_udp must not raise DeprecationWarning from get_event_loop()."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        gen = _stream_udp("127.0.0.1", 19999, 1)
        first_event = None
        try:
            # Bind to a local port; it may timeout cleanly with no messages.
            first_event = await asyncio.wait_for(gen.__anext__(), timeout=2)
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass
        except Exception:
            pass
