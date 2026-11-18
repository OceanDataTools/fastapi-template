"""Wait until the configured database accepts queries, creating it if missing.

Run before migrations in ``entrypoint.sh``::

    python -m app.scripts.wait_for_db

- SQLite: nothing to wait for; exits immediately.
- PostgreSQL: connects to ``settings.database_url`` and runs ``SELECT 1``,
  retrying with exponential backoff. If the server is up but the target
  database doesn't exist, it is created via the ``postgres`` maintenance
  database (inside the same retry loop). Exits non-zero after
  ``DB_WAIT_TIMEOUT`` seconds (default 60).
"""

import asyncio
import os
import sys
import time

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

DEFAULT_TIMEOUT = 60.0
MAX_BACKOFF = 5.0


def _is_missing_database(exc: BaseException) -> bool:
    """True if the error chain says the target database does not exist."""
    while exc is not None:
        if type(exc).__name__ == "InvalidCatalogNameError":
            return True
        exc = exc.__cause__ or exc.__context__  # type: ignore[assignment]
    return False


async def _ping(url: URL) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def _create_database(url: URL) -> None:
    db_name = url.database
    admin_url = url.set(database="postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if not exists:
                quoted = '"' + str(db_name).replace('"', '""') + '"'
                await conn.execute(text(f"CREATE DATABASE {quoted}"))
                print(f"Created database '{db_name}'.", flush=True)
    finally:
        await engine.dispose()


async def wait_for_db(url: URL, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    delay = 0.5
    attempt = 0
    while True:
        attempt += 1
        try:
            await _ping(url)
            return
        except Exception as exc:
            if _is_missing_database(exc):
                try:
                    await _create_database(url)
                    continue  # re-check with a real query against the new DB
                except Exception as create_exc:
                    exc = create_exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"database not ready after {timeout:.0f}s "
                    f"({attempt} attempts): {type(exc).__name__}: {exc}"
                ) from exc
            print(
                f"Database not ready (attempt {attempt}: {type(exc).__name__}); "
                f"retrying in {min(delay, remaining):.1f}s...",
                flush=True,
            )
            await asyncio.sleep(min(delay, remaining))
            delay = min(delay * 2, MAX_BACKOFF)


def main() -> int:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        return 0

    timeout = float(os.getenv("DB_WAIT_TIMEOUT", DEFAULT_TIMEOUT))
    safe_url = url.render_as_string(hide_password=True)
    print(f"Waiting for database at {safe_url} (timeout {timeout:.0f}s)...", flush=True)
    try:
        asyncio.run(wait_for_db(url, timeout))
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    print("Database is ready.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
