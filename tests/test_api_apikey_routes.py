"""Tests for GET /api/v1/apikeys/routes (routes selectable as API key permissions)."""

import pytest


@pytest.mark.asyncio
async def test_list_routes_returns_apikey_routes(client, auth_headers):
    # Regression for #51: on FastAPI >= 0.137, app.routes holds _IncludedRouter
    # objects instead of APIRoutes, and this endpoint returned [].
    resp = await client.get("/api/v1/apikeys/routes", headers=auth_headers)
    assert resp.status_code == 200
    found = {(r["route"], tuple(sorted(r["methods"]))) for r in resp.json()}
    assert found == {
        ("/api/v1/examples/any_auth", ("GET",)),
        ("/api/v1/examples/apikey_auth", ("GET",)),
        ("/api/v1/examples/post_auth", ("POST",)),
    }


@pytest.mark.asyncio
async def test_list_routes_requires_auth(client):
    resp = await client.get("/api/v1/apikeys/routes")
    assert resp.status_code == 401
