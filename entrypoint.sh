#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if present; when running via Docker the env vars are expected to
# be injected by the runtime (docker-compose env_file, -e flags, etc.).
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ ! -f "./db.sqlite3" ]; then
    echo "Creating SQLite database file..."
    touch ./db.sqlite3
fi

echo "Running Alembic migrations..."
poetry run alembic upgrade head

CMD="uvicorn app.main:app --host 0.0.0.0 --port 8000"

if [ "$ENVIRONMENT" = "Development" ]; then
    echo "Starting in Development mode with auto-reload..."
    exec poetry run $CMD --reload
else
    echo "Starting in Production mode..."
    exec poetry run $CMD
fi
