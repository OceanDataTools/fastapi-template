"""Tests for POST /api/v1/auth/register (issue #41)."""

import secrets

import pytest


async def _register_and_login(client):
    username = f"reg_{secrets.token_hex(4)}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "full_name": "Registered User",
            "email": f"{username}@test.example",
            "password": "pw-123456",
        },
    )
    assert resp.status_code == 201
    login = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": "pw-123456"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_registered_user_gets_user_role(client):
    headers = await _register_and_login(client)
    resp = await client.get("/api/v1/profile", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["user"]


@pytest.mark.asyncio
async def test_registered_user_can_use_jwt_endpoint(client):
    headers = await _register_and_login(client)
    resp = await client.get("/api/v1/examples/jwt_auth", headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_registered_user_is_not_admin(client):
    headers = await _register_and_login(client)
    resp = await client.get("/api/v1/examples/admin_auth", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_registration_without_full_name(client):
    username = f"reg_{secrets.token_hex(4)}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.example",
            "password": "pw-123456",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["full_name"] is None
