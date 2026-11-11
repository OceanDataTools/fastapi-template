"""
Tests for WebSocket authentication (issue #39):

- JWT users must still exist, be enabled and have a role.
- /api/v1/ws/data-server accepts API keys holding a (route, WEBSOCKET)
  permission; /api/v1/ws/test-connection does not.
- The data-server proxy refuses client 'publish' requests.
- Opted-in WebSocket routes are listed by GET /api/v1/apikeys/routes.

Uses starlette's synchronous TestClient because httpx does not support
WebSocket. The data-server proxy is pointed at a throwaway in-process
websockets server standing in for the CachedDataServer.
"""

import asyncio
import json
import secrets
import socket
import threading
from datetime import datetime, timedelta, timezone

import pytest
import websockets
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import WEBSOCKET_METHOD, create_access_jwt
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.users import create_user
from app.main import app
from app.models import APIKey, APIKeyPermission, User
from app.utils import get_apikey_hash, get_password_hash

# Seed through the app's own session factory. conftest points DATABASE_URL at
# the test database before the app is imported; importing conftest here
# instead would load it a second time under another module name and create a
# second, empty database.
_TestSession = AsyncSessionLocal

DATA_SERVER = "/api/v1/ws/data-server"
TEST_CONNECTION = "/api/v1/ws/test-connection"


def _client() -> TestClient:
    # The WebSocket endpoints authenticate with AsyncSessionLocal directly, so
    # no dependency overrides are needed.
    return TestClient(app, raise_server_exceptions=False)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _make_user(roles="user", disabled=False) -> str:
    username = f"ws_{secrets.token_hex(4)}"
    async with _TestSession() as session:
        user = await create_user(
            session,
            username=username,
            full_name="WS Test",
            email=f"{username}@test.example",
            hashed_password=get_password_hash("pw"),
            roles=roles,
        )
        if disabled:
            user.disabled = True
            await session.commit()
    return username


async def _make_apikey(
    username="admin",
    permissions=((DATA_SERVER, WEBSOCKET_METHOD),),
    revoked=False,
    expires_at=None,
) -> str:
    raw_key = secrets.token_urlsafe(32)
    async with _TestSession() as session:
        user = (
            await session.execute(
                User.__table__.select().where(User.username == username)
            )
        ).first()
        apikey = APIKey(
            user_id=user.id,
            key_hash=get_apikey_hash(raw_key),
            name="ws test",
            revoked=revoked,
            expires_at=expires_at,
        )
        session.add(apikey)
        await session.flush()
        for route, method in permissions:
            session.add(
                APIKeyPermission(apikey_id=apikey.id, route=route, method=method)
            )
        await session.commit()
    return raw_key


def _token_for(username: str) -> str:
    return create_access_jwt({"sub": username})


def _assert_rejected(path: str, **kwargs):
    with pytest.raises(WebSocketDisconnect) as exc:
        with _client().websocket_connect(path, **kwargs) as ws:
            ws.receive_text()
    assert exc.value.code == 1008


# ---------------------------------------------------------------------------
# Fake CachedDataServer
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_cds(monkeypatch):
    """Run a websockets server that records and echoes what it receives."""
    received: list[str] = []
    started = threading.Event()
    loop = asyncio.new_event_loop()
    stop: asyncio.Future = loop.create_future()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def handler(ws):
        try:
            async for message in ws:
                received.append(message)
                await ws.send(json.dumps({"echo": json.loads(message)}))
        except websockets.ConnectionClosed:
            pass

    async def serve():
        server = await websockets.serve(handler, "127.0.0.1", port)
        started.set()
        await stop
        # Don't let a proxy connection that is still closing hold up teardown.
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2)
        except asyncio.TimeoutError:
            pass

    thread = threading.Thread(
        target=lambda: loop.run_until_complete(serve()), daemon=True
    )
    thread.start()
    assert started.wait(5)

    monkeypatch.setattr(settings, "cached_data_server_host", "127.0.0.1")
    monkeypatch.setattr(settings, "cached_data_server_port", port)
    yield received
    loop.call_soon_threadsafe(stop.set_result, None)
    thread.join(5)
    if not thread.is_alive():
        loop.close()


# ---------------------------------------------------------------------------
# JWT: the user must still exist, be enabled and have a role
# ---------------------------------------------------------------------------


class TestJwtUserChecks:

    @pytest.mark.parametrize("path", [DATA_SERVER, TEST_CONNECTION])
    def test_unknown_user_rejected(self, path):
        _assert_rejected(f"{path}?token={_token_for('no_such_user')}")

    @pytest.mark.parametrize("path", [DATA_SERVER, TEST_CONNECTION])
    def test_disabled_user_rejected(self, path):
        username = _run(_make_user(disabled=True))
        _assert_rejected(f"{path}?token={_token_for(username)}")

    @pytest.mark.parametrize("path", [DATA_SERVER, TEST_CONNECTION])
    def test_user_without_roles_rejected(self, path):
        username = _run(_make_user(roles=[]))
        _assert_rejected(f"{path}?token={_token_for(username)}")

    @pytest.mark.parametrize("path", [DATA_SERVER, TEST_CONNECTION])
    def test_garbage_token_rejected(self, path):
        _assert_rejected(f"{path}?token=not-a-jwt")

    def test_bearer_header_accepted(self, fake_cds, access_token):
        with _client().websocket_connect(
            DATA_SERVER, headers={"Authorization": f"Bearer {access_token}"}
        ) as ws:
            ws.send_text(json.dumps({"type": "fields"}))
            assert ws.receive_json() == {"echo": {"type": "fields"}}


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


class TestApiKeyAuth:

    def test_header_key_accepted(self, fake_cds):
        key = _run(_make_apikey())
        with _client().websocket_connect(DATA_SERVER, headers={"X-API-Key": key}) as ws:
            ws.send_text(json.dumps({"type": "fields"}))
            assert ws.receive_json() == {"echo": {"type": "fields"}}

    def test_query_key_accepted(self, fake_cds):
        key = _run(_make_apikey())
        with _client().websocket_connect(f"{DATA_SERVER}?api_key={key}") as ws:
            ws.send_text(json.dumps({"type": "fields"}))
            assert ws.receive_json() == {"echo": {"type": "fields"}}

    def test_unknown_key_rejected(self):
        _assert_rejected(DATA_SERVER, headers={"X-API-Key": "nope"})

    def test_revoked_key_rejected(self):
        key = _run(_make_apikey(revoked=True))
        _assert_rejected(DATA_SERVER, headers={"X-API-Key": key})

    def test_expired_key_rejected(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        key = _run(_make_apikey(expires_at=past))
        _assert_rejected(DATA_SERVER, headers={"X-API-Key": key})

    def test_key_without_websocket_permission_rejected(self):
        key = _run(_make_apikey(permissions=((DATA_SERVER, "GET"),)))
        _assert_rejected(DATA_SERVER, headers={"X-API-Key": key})

    def test_key_for_other_route_rejected(self):
        key = _run(_make_apikey(permissions=(("/api/v1/other", WEBSOCKET_METHOD),)))
        _assert_rejected(DATA_SERVER, headers={"X-API-Key": key})

    def test_key_of_disabled_user_rejected(self):
        username = _run(_make_user(disabled=True))
        key = _run(_make_apikey(username=username))
        _assert_rejected(DATA_SERVER, headers={"X-API-Key": key})

    def test_jwt_and_key_together_rejected(self, access_token):
        key = _run(_make_apikey())
        _assert_rejected(
            f"{DATA_SERVER}?token={access_token}", headers={"X-API-Key": key}
        )

    def test_test_connection_refuses_api_keys(self):
        key = _run(_make_apikey(permissions=((TEST_CONNECTION, WEBSOCKET_METHOD),)))
        _assert_rejected(TEST_CONNECTION, headers={"X-API-Key": key})


# ---------------------------------------------------------------------------
# Proxy behaviour
# ---------------------------------------------------------------------------


class TestDataServerProxy:

    def test_publish_refused_and_not_forwarded(self, fake_cds, access_token):
        publish = {"type": "publish", "data": {"timestamp": 1.0, "fields": {"X": 1}}}
        with _client().websocket_connect(f"{DATA_SERVER}?token={access_token}") as ws:
            ws.send_text(json.dumps(publish))
            reply = ws.receive_json()
            assert reply["type"] == "publish"
            assert reply["status"] == 403

            # The connection stays usable, and only the non-publish request
            # reached the CDS.
            ws.send_text(json.dumps({"type": "fields"}))
            assert ws.receive_json() == {"echo": {"type": "fields"}}

        assert [json.loads(m)["type"] for m in fake_cds] == ["fields"]

    def test_subscribe_forwarded(self, fake_cds, access_token):
        subscribe = {"type": "subscribe", "fields": {"S330Lat": {"seconds": -1}}}
        with _client().websocket_connect(f"{DATA_SERVER}?token={access_token}") as ws:
            ws.send_text(json.dumps(subscribe))
            assert ws.receive_json() == {"echo": subscribe}


# ---------------------------------------------------------------------------
# Route listing for the API key UI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apikey_routes_lists_data_server_only(client, auth_headers):
    resp = await client.get("/api/v1/apikeys/routes", headers=auth_headers)
    assert resp.status_code == 200
    ws_routes = {r["route"]: r for r in resp.json() if WEBSOCKET_METHOD in r["methods"]}
    assert set(ws_routes) == {DATA_SERVER}
    assert ws_routes[DATA_SERVER]["methods"] == [WEBSOCKET_METHOD]
