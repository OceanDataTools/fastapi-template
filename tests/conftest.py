"""
Shared fixtures for the API test suite.

Backend selection
-----------------
- Default: a temporary SQLite file (not in-memory, so all async connections
  share one database). Schema is built with ``Base.metadata.create_all`` and
  roles + the admin user are seeded here.
- ``TEST_DATABASE_URL`` set (e.g.
  ``postgresql+asyncpg://postgres:postgres@localhost:5432/postgres``): a
  throwaway database ``test_<random>`` is created on that server, the schema
  is built with ``alembic upgrade head`` (so migrations are exercised, and the
  initial migration seeds roles + admin from ``DEFAULT_ADMIN_*``), and the
  database is dropped at the end of the session.

Postgres-only tests: mark them ``@pytest.mark.postgres``; they are skipped
on the SQLite run. ``TEST_DB_IS_POSTGRES`` is importable for finer checks.

All env vars are set before any app module is imported so pydantic-settings
picks them up.
"""

import asyncio
import os
import secrets
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

# ── must come before any app imports ──────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
TEST_DB_IS_POSTGRES = bool(_TEST_DATABASE_URL)

_TEST_DB_PATH = None  # SQLite file path
_PG_SERVER_URL = None  # maintenance-DB URL used to create/drop the test DB
_PG_TEST_DB = None  # name of the throwaway Postgres database


def _pg_admin_engine():
    return create_async_engine(_PG_SERVER_URL, isolation_level="AUTOCOMMIT")


async def _pg_create_db() -> None:
    engine = _pg_admin_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{_PG_TEST_DB}"'))
    finally:
        await engine.dispose()


async def _pg_drop_db() -> None:
    engine = _pg_admin_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(f'DROP DATABASE IF EXISTS "{_PG_TEST_DB}" WITH (FORCE)')
            )
    finally:
        await engine.dispose()


_pg_dropped = False


def _pg_drop_db_once() -> None:
    global _pg_dropped
    if _pg_dropped:
        return
    _pg_dropped = True
    asyncio.run(_pg_drop_db())


if TEST_DB_IS_POSTGRES:
    _server = make_url(_TEST_DATABASE_URL)
    if _server.get_backend_name() != "postgresql":
        raise RuntimeError(
            f"TEST_DATABASE_URL must be a PostgreSQL URL, got '{_server.drivername}'"
        )
    _server = _server.set(drivername="postgresql+asyncpg")
    _PG_SERVER_URL = _server
    _PG_TEST_DB = f"test_{secrets.token_hex(6)}"
    # Dropped in pytest_unconfigure, which runs even after setup/collection
    # errors or Ctrl-C (atexit is too late: asyncio can't run at shutdown).
    asyncio.run(_pg_create_db())
    os.environ["DATABASE_URL"] = _server.set(database=_PG_TEST_DB).render_as_string(
        hide_password=False
    )
else:
    _TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".sqlite3")
    os.close(_TEST_DB_FD)  # we only need the path; close the fd immediately
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-xxxxx")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")
os.environ.setdefault("ENVIRONMENT", "Development")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
# The seeded admin the tests log in as. Forced (not setdefault) so a local
# .env or shell value can't change it; the Alembic seed reads these too.
os.environ["DEFAULT_ADMIN_USERNAME"] = "admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "adminpass"
os.environ["DEFAULT_ADMIN_FULLNAME"] = "Test Admin"
os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@test.example"
# ──────────────────────────────────────────────────────────────────────────────

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import create_access_jwt, create_refresh_jwt
from app.deps import get_async_session
from app.main import app
from app.models import Base, Role
from app.utils import get_password_hash
from app.db.users import create_user


# ---------------------------------------------------------------------------
# Postgres-only marker
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "postgres: test requires PostgreSQL (set TEST_DATABASE_URL)"
    )


def pytest_unconfigure(config):
    if TEST_DB_IS_POSTGRES:
        _pg_drop_db_once()


def pytest_collection_modifyitems(config, items):
    if TEST_DB_IS_POSTGRES:
        return
    skip = pytest.mark.skip(reason="requires PostgreSQL (set TEST_DATABASE_URL)")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Shared test engine
# ---------------------------------------------------------------------------

# asyncpg connections are bound to the event loop that opened them, and
# pytest-asyncio gives each test its own loop, so don't pool on Postgres.
_TEST_ENGINE = create_async_engine(
    os.environ["DATABASE_URL"],
    future=True,
    echo=False,
    **({"poolclass": NullPool} if TEST_DB_IS_POSTGRES else {}),
)

if not TEST_DB_IS_POSTGRES:

    @event.listens_for(_TEST_ENGINE.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


_TestSession = sessionmaker(_TEST_ENGINE, expire_on_commit=False, class_=AsyncSession)


# ---------------------------------------------------------------------------
# Session-scoped DB setup
# ---------------------------------------------------------------------------

def _alembic_upgrade_head() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    # env.py reads the URL from app.config.settings (i.e. DATABASE_URL above)
    command.upgrade(cfg, "head")


async def _setup_sqlite() -> None:
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


async def _teardown_sqlite() -> None:
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _TEST_ENGINE.dispose()


@pytest.fixture(scope="session", autouse=True)
def _db():
    """Synchronous session fixture so the DB is ready before any test event loop starts."""
    if TEST_DB_IS_POSTGRES:
        # Alembic's env.py runs its own event loop, so call it outside one.
        _alembic_upgrade_head()
        yield
        asyncio.run(_TEST_ENGINE.dispose())
        # the database itself is dropped in pytest_unconfigure
    else:
        asyncio.run(_setup_sqlite())
        yield
        asyncio.run(_teardown_sqlite())
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """Async SQLAlchemy session connected to the test database."""
    async with _TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    """AsyncClient wired to the FastAPI app with the test DB."""
    app.dependency_overrides[get_async_session] = _override_get_session
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
