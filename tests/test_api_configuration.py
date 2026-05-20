"""
Tests for /api/v1/configuration/ — focusing on path-traversal security (Bug #1)
and authentication enforcement.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRAVERSAL_PATHS = [
    "../../etc/shadow",
    "../../etc/passwd",
    "../app/config.py",
    "/etc/shadow",
    "/opt/openrvdas/web_backend/app/config.py",
]

_BAD_ROOT_PATHS = [
    "uploads/cruise.yaml",
    "config/cruise.yaml",
    "cruise.yaml",
]


# ---------------------------------------------------------------------------
# POST /api/v1/configuration/ (load)
# ---------------------------------------------------------------------------

class TestLoadConfiguration:

    @pytest.mark.asyncio
    async def test_load_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/configuration/",
            params={"config_filepath": "local/cruise.yaml"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", _TRAVERSAL_PATHS)
    async def test_load_rejects_path_traversal(self, client, auth_headers, path):
        resp = await client.post(
            "/api/v1/configuration/",
            params={"config_filepath": path},
            headers=auth_headers,
        )
        assert resp.status_code == 400, f"Expected 400 for path {path!r}, got {resp.status_code}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", _BAD_ROOT_PATHS)
    async def test_load_rejects_disallowed_root(self, client, auth_headers, path):
        resp = await client.post(
            "/api/v1/configuration/",
            params={"config_filepath": path},
            headers=auth_headers,
        )
        assert resp.status_code == 400, f"Expected 400 for path {path!r}, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_load_returns_404_for_missing_file(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/configuration/",
            params={"config_filepath": "local/does_not_exist_xyzzy.yaml"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/configuration/preview
# ---------------------------------------------------------------------------

class TestPreviewConfiguration:

    @pytest.mark.asyncio
    async def test_preview_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/configuration/preview",
            params={"config_filepath": "local/cruise.yaml"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", _TRAVERSAL_PATHS)
    async def test_preview_rejects_path_traversal(self, client, auth_headers, path):
        resp = await client.post(
            "/api/v1/configuration/preview",
            params={"config_filepath": path},
            headers=auth_headers,
        )
        assert resp.status_code == 400, f"Expected 400 for path {path!r}, got {resp.status_code}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", _BAD_ROOT_PATHS)
    async def test_preview_rejects_disallowed_root(self, client, auth_headers, path):
        resp = await client.post(
            "/api/v1/configuration/preview",
            params={"config_filepath": path},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_preview_returns_404_for_missing_file(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/configuration/preview",
            params={"config_filepath": "local/does_not_exist_xyzzy.yaml"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/configuration/files
# ---------------------------------------------------------------------------

class TestListConfigFiles:

    @pytest.mark.asyncio
    async def test_files_requires_auth(self, client):
        resp = await client.get("/api/v1/configuration/files")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_files_root_lists_allowed_roots(self, client, auth_headers):
        resp = await client.get("/api/v1/configuration/files", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "entries" in body
        for entry in body["entries"]:
            assert entry["name"] in ("local", "test")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["../../etc", "../app", "/etc"])
    async def test_files_rejects_path_traversal(self, client, auth_headers, path):
        resp = await client.get(
            "/api/v1/configuration/files",
            params={"path": path},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_files_rejects_disallowed_root(self, client, auth_headers):
        resp = await client.get(
            "/api/v1/configuration/files",
            params={"path": "uploads"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
