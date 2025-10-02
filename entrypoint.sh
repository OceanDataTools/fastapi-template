#!/usr/bin/env bash
set -e

START_DIR="$(pwd)"

# --- Ensure we’re in the script’s directory (project root) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export $(grep -v '^#' .env | xargs)

if [ -n "$DB_HOST" ]; then
    echo "Waiting for database at $DB_HOST:$DB_PORT..."
    while ! nc -z "$DB_HOST" "$DB_PORT"; do
        echo -n "."
        sleep 1
    done
    echo "Database is ready!"

    echo "Ensuring database '$POSTGRES_DB' exists..."
    poetry run python3 - <<'PYTHON_EOF'
import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import asyncpg.exceptions

db_name = os.getenv("POSTGRES_DB")
db_url = f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/postgres"

engine = create_async_engine(db_url, future=True)

async def create_db():
    async with engine.connect() as conn:
        # Ensure autocommit
        await conn.run_sync(lambda sync_conn: sync_conn.execution_options(isolation_level="AUTOCOMMIT"))
        try:
            await conn.run_sync(lambda sync_conn: sync_conn.execute(text(f'CREATE DATABASE "{db_name}"')))
            print(f"Database '{db_name}' created.")
        except ProgrammingError as e:
            # Catch duplicate DB error and ignore
            if "already exists" in str(e):
                print(f"Skipping DB creation, '{db_name}' already exists.")
            else:
                raise
    await engine.dispose()

asyncio.run(create_db())
PYTHON_EOF
else
    if [ ! -f "./db.sqlite3" ]; then
        echo "Creating SQLite database file..."
        touch ./db.sqlite3
    fi
fi

echo "Running Alembic migrations..."
poetry run alembic upgrade head

# Default command (can be overridden via CMD)
CMD="uvicorn app.main:app --host 0.0.0.0 --port 8000"

if [ "$ENVIRONMENT" = "Development" ]; then
  echo "Starting in Development mode with auto-reload..."
  exec poetry run $CMD --reload
else
  echo "Starting in Production mode..."
  exec poetry run $CMD
fi
