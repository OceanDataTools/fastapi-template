"""Tests for POST /api/v1/auth/register (issue #41)."""

import secrets

import pytest
from fastapi import HTTPException

from app.auth import jwt_required
from app.db.users import get_user_by_username


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
    return username, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_registered_user_gets_user_role(client):
    _, headers = await _register_and_login(client)
    resp = await client.get("/api/v1/profile", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["user"]


# The two tests below call the jwt_required() dependency directly rather
# than going through /api/v1/examples, because projects built on this
# template (e.g. openrvdas) don't mount the examples router.


@pytest.mark.asyncio
async def test_registered_user_passes_jwt_required(client, db_session):
    username, _ = await _register_and_login(client)
    user = await get_user_by_username(db_session, username)
    assert await jwt_required()(user) is user


@pytest.mark.asyncio
async def test_registered_user_is_not_admin(client, db_session):
    username, _ = await _register_and_login(client)
    user = await get_user_by_username(db_session, username)
    with pytest.raises(HTTPException) as exc:
        await jwt_required(required_roles=("admin",))(user)
    assert exc.value.status_code == 403


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
