"""
Shared fixtures for the API test suite.

Uses a temporary SQLite file (not in-memory) so all async connections share
the same database — async SQLAlchemy + aiosqlite do not reliably share a
single in-memory database across connections even with StaticPool.

The DATABASE_URL env var is overridden before any app module is imported so
pydantic-settings picks up the test database URL.
"""

import os
import tempfile

# ── must come before any app imports ──────────────────────────────────────────
_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".sqlite3")
os.close(_TEST_DB_FD)  # we only need the path; close the fd immediately

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-xxxxx")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")
os.environ.setdefault("ENVIRONMENT", "Development")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
# ──────────────────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth import create_access_jwt, create_refresh_jwt
from app.deps import get_async_server_api, get_async_session
from app.main import app
from app.models import Base, Role
from app import models_openrvdas as _models_openrvdas  # noqa: F401 — registers ORM tables on Base.metadata
from app.utils import get_password_hash
from app.db.users import create_user

# ---------------------------------------------------------------------------
# Shared test engine — file-backed SQLite shared by all test sessions.
# ---------------------------------------------------------------------------

_TEST_ENGINE = create_async_engine(
    f"sqlite+aiosqlite:///{_TEST_DB_PATH}",
    future=True,
    echo=False,
)


@event.listens_for(_TEST_ENGINE.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_TestSession = sessionmaker(_TEST_ENGINE, expire_on_commit=False, class_=AsyncSession)


# ---------------------------------------------------------------------------
# Session-scoped DB setup: create tables + seed roles + admin user once.
# ---------------------------------------------------------------------------

async def _setup_db() -> None:
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _TestSession() as session:
        async with session.begin():
            session.add_all([Role(name="admin"), Role(name="user")])

    async with _TestSession() as session:
        await create_user(
            session,
            username="admin",
            full_name="Test Admin",
            email="admin@test.example",
            hashed_password=get_password_hash("adminpass"),
            roles="admin",
        )


async def _teardown_db() -> None:
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _TEST_ENGINE.dispose()


@pytest.fixture(scope="session", autouse=True)
def _db():
    """Synchronous session fixture so the DB is ready before any test event loop starts."""
    import asyncio
    asyncio.run(_setup_db())
    yield
    asyncio.run(_teardown_db())
    try:
        os.unlink(_TEST_DB_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Dependency overrides
# ---------------------------------------------------------------------------

async def _override_get_session():
    async with _TestSession() as session:
        yield session


class _AsyncServerAPIMock:
    """Stub that satisfies get_async_server_api without the real lifespan."""
    def __getattr__(self, name):
        return AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """Async SQLAlchemy session connected to the test database.

    Use this in tests that need to seed data before making API calls.
    Each test gets a fresh session; data persists for the life of the session.
    """
    async with _TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    """AsyncClient wired to the FastAPI app with the test DB and a mocked
    AsyncFastAPIServerAPI (so the OpenRVDAS lifespan need not run)."""
    app.dependency_overrides[get_async_session] = _override_get_session
    app.dependency_overrides[get_async_server_api] = lambda: _AsyncServerAPIMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def access_token():
    """Valid access JWT for the seeded admin user."""
    return create_access_jwt({"sub": "admin", "roles": ["admin"]})


@pytest.fixture
def refresh_token():
    """Refresh JWT for the seeded admin user (type='refresh')."""
    return create_refresh_jwt({"sub": "admin", "roles": ["admin"]})


@pytest.fixture
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}
