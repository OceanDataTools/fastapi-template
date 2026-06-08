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
    # Traversal via an allowed root prefix — caught by normpath, not the root check
    "local/../../etc/passwd",
    "test/../../etc/shadow",
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

    @pytest.mark.asyncio
    async def test_load_resolves_symlinked_file(
        self, client, auth_headers, tmp_path, monkeypatch
    ):
        """A config file reachable via a symlinked local/ should not return 400."""
        import app.api.configuration as config_mod

        fake_root = tmp_path / "openrvdas"
        fake_root.mkdir()

        external = tmp_path / "vessel_configs"
        external.mkdir()
        (external / "NBP_cruise.yaml").write_text("cruise:\n  id: NBP\n")

        (fake_root / "local").symlink_to(external)

        monkeypatch.setattr(config_mod, "_OPENRVDAS_DIR", fake_root)

        resp = await client.post(
            "/api/v1/configuration/",
            params={"config_filepath": "local/NBP_cruise.yaml"},
            headers=auth_headers,
        )
        # The path should not be rejected by the traversal guard.
        # A 400 for config-content reasons (e.g. missing 'loggers' key) or a
        # 503 (OpenRVDAS libs unavailable in test env) are both acceptable —
        # they mean _resolve_config_path succeeded and the symlink was followed.
        if resp.status_code == 400:
            assert "traversal" not in resp.text.lower(), (
                f"Symlinked path was rejected by traversal guard: {resp.text}"
            )


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

    @pytest.mark.asyncio
    async def test_preview_resolves_symlinked_file(
        self, client, auth_headers, tmp_path, monkeypatch
    ):
        """A config file reachable via a symlinked local/ should not return 400."""
        import app.api.configuration as config_mod

        fake_root = tmp_path / "openrvdas"
        fake_root.mkdir()

        external = tmp_path / "vessel_configs"
        external.mkdir()
        (external / "NBP_cruise.yaml").write_text("cruise:\n  id: NBP\n")

        (fake_root / "local").symlink_to(external)

        monkeypatch.setattr(config_mod, "_OPENRVDAS_DIR", fake_root)

        resp = await client.post(
            "/api/v1/configuration/preview",
            params={"config_filepath": "local/NBP_cruise.yaml"},
            headers=auth_headers,
        )
        # 503 means OpenRVDAS libs aren't available in the test env — that's fine;
        # it means _resolve_config_path succeeded and the symlink was followed.
        assert resp.status_code != 400, f"Symlinked path was rejected: {resp.text}"


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

    @pytest.mark.asyncio
    async def test_files_traverses_symlinked_directory(
        self, client, auth_headers, tmp_path, monkeypatch
    ):
        """local/ pointing outside _OPENRVDAS_DIR via a symlink should be traversable."""
        import app.api.configuration as config_mod

        # Minimal fake openrvdas root.
        fake_root = tmp_path / "openrvdas"
        fake_root.mkdir()

        # Config files live outside fake_root (simulates a vessel-specific repo).
        external = tmp_path / "vessel_configs"
        external.mkdir()
        (external / "NBP_cruise.yaml").write_text("mode: port\n")
        (external / "subdir").mkdir()

        # local/ → external (symlink pointing outside _OPENRVDAS_DIR)
        (fake_root / "local").symlink_to(external)

        monkeypatch.setattr(config_mod, "_OPENRVDAS_DIR", fake_root)

        resp = await client.get(
            "/api/v1/configuration/files",
            params={"path": "local"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        names = [e["name"] for e in body["entries"]]
        assert "NBP_cruise.yaml" in names
        assert "subdir" in names
        # rel_path must remain within the logical tree, not leak the real path.
        for entry in body["entries"]:
            assert entry["rel_path"].startswith("local")
