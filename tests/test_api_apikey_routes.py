"""Tests for GET /api/v1/apikeys/routes (routes selectable as API key permissions)."""

import pytest

EXPECTED_ROUTES = {
    ("/api/v1/ws/data-server", ("WEBSOCKET",)),
    ("/api/v1/configuration/files", ("GET",)),
    ("/api/v1/configuration/", ("GET",)),
    ("/api/v1/configuration/preview", ("POST",)),
    ("/api/v1/configuration/", ("POST",)),
    ("/api/v1/configuration/render-template", ("POST",)),
    ("/api/v1/configuration/verify-parser", ("POST",)),
    ("/api/v1/connection/serial-ports", ("GET",)),
    ("/api/v1/connection/cds-fields", ("GET",)),
    ("/api/v1/connection/check-port", ("GET",)),
    ("/api/v1/connection/stream", ("POST",)),
    ("/api/v1/modes/{mode_id}/activate", ("POST",)),
    ("/api/v1/configs/{config_id}/activate", ("POST",)),
}


@pytest.mark.asyncio
async def test_list_routes_returns_apikey_routes(client, auth_headers):
    # Regression for #53 (port of #51): on FastAPI >= 0.137, app.routes holds
    # _IncludedRouter objects instead of APIRoutes/APIWebSocketRoutes, and this
    # endpoint returned [].
    resp = await client.get("/api/v1/apikeys/routes", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    found = {(r["route"], tuple(sorted(r["methods"]))) for r in body}
    assert found == EXPECTED_ROUTES
    assert len(body) == len(EXPECTED_ROUTES)


@pytest.mark.asyncio
async def test_list_routes_requires_auth(client):
    resp = await client.get("/api/v1/apikeys/routes")
    assert resp.status_code == 401
