"""Tests for POST /api/v1/auth/token and related auth behaviour."""

import pytest


@pytest.mark.asyncio
async def test_login_valid_credentials(client):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "adminpass"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "nobody", "password": "anything"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_without_token(client):
    resp = await client.get("/api/v1/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_valid_token(client, auth_headers):
    resp = await client.get("/api/v1/profile", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"



@pytest.mark.asyncio
async def test_expired_token_rejected(client):
    from datetime import timedelta
    from app.auth import create_access_jwt
    expired = create_access_jwt(
        {"sub": "admin", "roles": ["admin"]},
        expires_delta=timedelta(seconds=-1),
    )
    resp = await client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401
