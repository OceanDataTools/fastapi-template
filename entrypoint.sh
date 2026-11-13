#!/usr/bin/env bash
# Container/local entrypoint: wait for the DB, run migrations, start uvicorn.
#
# Configuration comes from the environment, falling back to ./.env (read by
# pydantic-settings in app/config.py). Variables already set in the
# environment always win over .env; this script never exports .env itself.
#
# Optional:
#   RUN_MIGRATIONS=false   skip `alembic upgrade head` (e.g. run it as a
#                          separate job / init container instead)
#   DB_WAIT_TIMEOUT=60     seconds to wait for the database before failing
set -eo pipefail

# --- Ensure we're in the script's directory (project root) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use poetry when available (local dev); in the image deps are installed
# into the system interpreter, so plain `python` works too.
if command -v poetry >/dev/null 2>&1; then
  RUN=(poetry run)
else
  RUN=()
fi

"${RUN[@]}" python -m app.scripts.wait_for_db

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Running Alembic migrations..."
  "${RUN[@]}" alembic upgrade head
else
  echo "RUN_MIGRATIONS=${RUN_MIGRATIONS}; skipping migrations."
fi

ENVIRONMENT="$("${RUN[@]}" python -c 'from app.config import settings; print(settings.environment)')"

CMD=(uvicorn app.main:app --host 0.0.0.0 --port 8000)

if [ "$ENVIRONMENT" = "Development" ]; then
  echo "Starting in Development mode with auto-reload..."
  exec "${RUN[@]}" "${CMD[@]}" --reload
else
  echo "Starting in Production mode..."
  exec "${RUN[@]}" "${CMD[@]}"
fi
