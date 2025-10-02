#!/usr/bin/env bash
set -e

START_DIR="$(pwd)"

# --- Ensure we’re in the script’s directory (project root) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 1. Create .env if missing ---
if [ ! -f ".env" ]; then
  echo "Creating default .env file..."

  SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

  cat > .env <<EOF
###############################################################################
# FOR TIMESCALE BACKED PROJECTS
###############################################################################
# This assumes the backend services are being run via docker. Change DB_HOST to
# 'localhost' if running locally
# DB_HOST=timescaledb
# DB_PORT=5432

########################
# POSTGRESQL Settings
########################
# POSTGRES_USER=postgres
# POSTGRES_PASSWORD=password
# POSTGRES_DB=odt_project_db

########################
# PGADMIN Settings
########################
# PGADMIN_DEFAULT_EMAIL=admin@example.com
# PGADMIN_DEFAULT_PASSWORD=password

###############################################################################
# FOR SQLITE BACKED PROJECTS
###############################################################################
DATABASE_URL=sqlite+aiosqlite:///./db.sqlite3

###############################################################################
# Default admin account - DELETE AFTER DB INITIALIZATION
###############################################################################
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=admin
DEFAULT_ADMIN_FULLNAME=Administrator
DEFAULT_ADMIN_EMAIL=odt_project_admin@oceandatatool.org

###############################################################################
# Backend settings
###############################################################################
SECRET_KEY=$SECRET_KEY
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
FRONTEND_URL=http://localhost:5173

###############################################################################
# Set to Production before deploying
###############################################################################
ENVIRONMENT=Development

###############################################################################
# Email Settings
###############################################################################
#SENDGRID_API_KEY=SG.xxxxxxx
#SENDGRID_FROM_EMAIL=noreply@oceandatatools.org
EOF
  echo ".env created."
else
  echo ".env already exists, skipping."
fi

# --- 2. Install dependencies ---
if command -v poetry &>/dev/null; then
  echo "Installing dependencies with Poetry..."
  poetry install --no-root
else
  echo "Poetry not found. Using venv + pip fallback..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
  elif [ -f "pyproject.toml" ]; then
    pip install poetry
    poetry export -f requirements.txt --without-hashes -o requirements.txt
    pip install -r requirements.txt
  fi
fi

# --- 3. Create db.sqlite3 if missing ---
if [ ! -f "./db.sqlite3" ]; then
  echo "Creating SQLite database file..."
  touch ./db.sqlite3
fi

cd "$START_DIR"

echo "Setup complete."
