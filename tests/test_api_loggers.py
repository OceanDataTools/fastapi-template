"""
Tests for /api/v1/loggers/ — including the Bug #2 fix (running field in LoggerOut).
"""

import pytest

from app.db import logger_crud, config_crud, logger_config_state_crud
from app.models_openrvdas import Config, Logger, LoggerConfigState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_logger(session, logger_id: str, config_id: str, running: bool):
    """Create a logger + config + state row so the CRUD returns real data.

    After committing, callers must invalidate the CRUD caches so the API sees
    the new data (direct inserts bypass the cache-aware CRUD write path).
    """
    session.add(Logger(id=logger_id))
    await session.flush()

    session.add(Config(id=config_id, logger_id=logger_id, config_json="{}"))
    await session.flush()

    session.add(LoggerConfigState(
        logger_id=logger_id,
        config_id=config_id,
        running=running,
        failed=False,
        pid=None,
        errors=None,
    ))
    await session.flush()


async def _bust_caches():
    """Force CRUD caches to re-read from DB on the next request."""
    await logger_crud._invalidate()
    await config_crud._invalidate()
    await logger_config_state_crud._invalidate()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestListLoggers:

    @pytest.mark.asyncio
    async def test_list_loggers_no_auth_is_public(self, client):
        """GET /loggers/ is intentionally public (unauthenticated read)."""
        resp = await client.get("/api/v1/loggers/")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_loggers_empty(self, client):
        resp = await client.get("/api/v1/loggers/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_logger_out_includes_running_field(self, client, db_session):
        """LoggerOut schema must include the 'running' field (Bug #2 regression guard)."""
        async with db_session.begin():
            await _seed_logger(db_session, "test-logger-run", "test-logger-run->on", running=True)
        await _bust_caches()

        resp = await client.get("/api/v1/loggers/")
        assert resp.status_code == 200
        loggers = resp.json()
        assert any(l["id"] == "test-logger-run" for l in loggers), "seeded logger not returned"
        entry = next(l for l in loggers if l["id"] == "test-logger-run")
        assert "running" in entry, "'running' field missing from LoggerOut response"
        assert entry["running"] is True

    @pytest.mark.asyncio
    async def test_logger_out_running_false_when_stopped(self, client, db_session):
        async with db_session.begin():
            await _seed_logger(db_session, "test-logger-stop", "test-logger-stop->on", running=False)
        await _bust_caches()

        resp = await client.get("/api/v1/loggers/")
        assert resp.status_code == 200
        loggers = resp.json()
        entry = next((l for l in loggers if l["id"] == "test-logger-stop"), None)
        assert entry is not None
        assert entry["running"] is False

    @pytest.mark.asyncio
    async def test_get_logger_not_found(self, client):
        resp = await client.get("/api/v1/loggers/nonexistent-logger")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_logger_by_id(self, client, db_session):
        async with db_session.begin():
            await _seed_logger(db_session, "test-logger-get", "test-logger-get->on", running=False)
        await _bust_caches()

        resp = await client.get("/api/v1/loggers/test-logger-get")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "test-logger-get"
        assert "running" in body
        assert "active_config" in body
        assert "configs" in body
