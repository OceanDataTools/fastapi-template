"""
Tests for WebSocket endpoints — focusing on the Bug #6 fix (refresh tokens
must be rejected with WS_1008_POLICY_VIOLATION).

Uses starlette's synchronous TestClient because httpx does not support WebSocket.
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from tests.conftest import _override_get_session
from app.deps import get_async_session


def _make_sync_client():
    app.dependency_overrides[get_async_session] = _override_get_session
    return TestClient(app, raise_server_exceptions=False)


class TestWebSocketTestConnection:

    def test_no_token_rejected(self):
        c = _make_sync_client()
        with pytest.raises(Exception):
            with c.websocket_connect("/api/v1/ws/test-connection"):
                pass

    def test_refresh_token_rejected(self, refresh_token):
        """A refresh JWT must be rejected (Bug #6).

        The server closes without accepting; starlette raises WebSocketDisconnect
        during websocket_connect() itself, not on a subsequent receive call.
        """
        c = _make_sync_client()
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(
                f"/api/v1/ws/test-connection?token={refresh_token}"
            ) as ws:
                ws.receive_json()

    def test_valid_access_token_accepted(self, access_token):
        """A valid access JWT must allow the WebSocket handshake to complete."""
        c = _make_sync_client()
        with c.websocket_connect(
            f"/api/v1/ws/test-connection?token={access_token}"
        ) as ws:
            # Server accepted — send a malformed start to trigger a clean error
            # response rather than waiting indefinitely.
            ws.send_json({"action": "start", "config_yaml": "class: TextFileReader\nkwargs:\n  file_spec: /dev/null\n"})
            # We should receive a status or error message, not a policy violation.
            msg = ws.receive_json()
            assert msg.get("type") in ("status", "error", "record")


class TestWebSocketDataServer:

    def test_refresh_token_rejected(self, refresh_token):
        """Refresh JWT must be rejected by the data-server proxy too (Bug #6)."""
        c = _make_sync_client()
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(
                f"/api/v1/ws/data-server?token={refresh_token}"
            ) as ws:
                ws.receive_json()

    def test_no_token_rejected(self):
        c = _make_sync_client()
        with pytest.raises(Exception):
            with c.websocket_connect("/api/v1/ws/data-server"):
                pass
