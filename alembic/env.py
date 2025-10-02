import asyncio
from logging.config import fileConfig
import os
import sys

from sqlalchemy import create_engine, event, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings  # DATABASE_URL, e.g., sqlite+aiosqlite:///./db.sqlite3

from alembic import context

# Add your app directory to sys.path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.models import Base  # declarative base

# Alembic Config
config = context.config
fileConfig(config.config_file_name)

DATABASE_URL = settings.database_url
print(DATABASE_URL)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


# --- Offline migrations ---
def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# --- Sync engine for autogenerate ---
def run_migrations_online_sync():
    # Strip async driver for sync engine
    sync_url = DATABASE_URL.replace("+aiosqlite", "")
    connectable = create_engine(sync_url, poolclass=pool.NullPool)

    # Enable foreign keys in SQLite
    if sync_url.startswith("sqlite"):
        @event.listens_for(connectable, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


# --- Async engine for runtime ---
async def run_migrations_online_async():
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:

        def do_migrations(sync_conn: Connection):
            context.configure(connection=sync_conn, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()

        # Run migrations in sync mode within async connection
        await connection.run_sync(do_migrations)

    await connectable.dispose()


# --- Entry point ---
def run():
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        # Use sync engine for autogenerate, async engine for runtime
        if config.get_main_option("autogenerate") == "true":
            run_migrations_online_sync()
        else:
            asyncio.run(run_migrations_online_async())


run()
