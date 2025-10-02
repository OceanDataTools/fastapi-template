#!/usr/bin/env bash
set -e

# Load env
export $(grep -v '^#' .env | xargs)

PROFILES=()

# Add development-only profile if in Development environment
[ "$ENVIRONMENT" = "Development" ] && PROFILES+=("development-only")

# Add timescale-db profile if DB_HOST is defined
[ -n "$DB_HOST" ] && PROFILES+=("timescale-db")

# Add sqlite-db profile if DATABASE_URL points to SQLite
[[ "$DATABASE_URL" == sqlite* ]] && PROFILES+=("sqlite-db")

# Add timescale-development only if timescale-db is present
if [[ " ${PROFILES[*]} " == *" timescale-db "* ]]; then
  PROFILES+=("timescale-development")
fi

if [ ${#PROFILES[@]} -gt 0 ]; then
  echo "Starting services with profiles: ${PROFILES[*]}"
  docker-compose $(for p in "${PROFILES[@]}"; do echo "--profile $p"; done) up -d
else
  echo "Starting only core services..."
  docker-compose up -d
fi
