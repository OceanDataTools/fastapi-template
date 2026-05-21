# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FastAPI-based backend providing JWT + API key authentication and user management. Designed to be extended with application-specific routes. Supports both SQLite (development) and PostgreSQL/TimescaleDB (production).

## Submodule & Git Workflow

`web_backend` and `web_frontend` are git submodules of the parent `openrvdas` repo. Their HEADs are detached by default; all branch work lives on the `openrvdas` branch.

After committing changes in a submodule:

```bash
git switch openrvdas           # reattach HEAD
git merge --ff-only <sha>      # fast-forward to your commit
git push origin openrvdas
```

Then update the parent repo's submodule pointer:

```bash
git -C /opt/openrvdas add web_backend web_frontend
git -C /opt/openrvdas commit -m "Update submodules: ..."
git -C /opt/openrvdas push origin <branch>
```

**Always run `poetry` from `/opt/openrvdas/web_backend`.** The parent repo has its own `/opt/openrvdas/pyproject.toml` (OpenRVDAS core deps). Running poetry from the repo root or `web_frontend` will pick that file up instead and resolve the wrong dependency set.

## Testing

```bash
poetry run pytest tests/ -q --tb=short
```

61 tests cover auth, loggers, configuration endpoints, WebSocket token validation, connection streaming, and `get_status`. The pre-commit hook runs them automatically on every commit.

**Cache invalidation in tests:** `CachedAsyncCRUDBase` caches DB reads in memory. Direct DB inserts (seeding test data) bypass the CRUD write path and won't invalidate the cache automatically. After seeding, call `await <crud>._invalidate()` for each affected CRUD object, otherwise the API will return stale data.

## Setup & Running

```bash
# Install dependencies and generate .env
./setup.sh

# Start with Docker (auto-selects db profile from .env)
./start.sh

# Or run directly (runs migrations then starts server)
./entrypoint.sh

# Run server manually
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Database Migrations

```bash
# Apply migrations
poetry run alembic upgrade head

# Create a new migration (after modifying models)
poetry run alembic revision --autogenerate -m "description"
```

**Important:** `alembic/env.py` imports models via `import app.models`. When adding new model files, import them in `env.py` after the existing import. New models must inherit from the same `Base` class in `app/models.py`.

## Linting & Formatting

```bash
poetry run black app/
poetry run isort app/
poetry run flake8 app/ --ignore=E501
poetry run mypy app/
```

Pre-commit hooks run black, isort, flake8, and mypy automatically on commit.

**Python version:** Keep `target-version` in `[tool.black]` (and the `python = "^X.Y"` constraint in `[tool.poetry.dependencies]`) in sync with the minimum Python version that OpenRVDAS ships on production. Don't bump these to match a dev machine's Python version.

## Architecture

### Request Flow

```
HTTP Request → FastAPI Route (app/api/*.py)
              → Auth dependency (app/auth.py decorators)
              → DB CRUD function (app/db/*.py)
              → SQLAlchemy AsyncSession (app/db/session.py)
              → PostgreSQL or SQLite
```

### Key Modules

- **`app/main.py`** — FastAPI app init, lifespan (calls `init_db`), CORS, router registration. Also hosts the `GET /api/v1/apikeys/routes` endpoint that lists all API-key-accessible routes.
- **`app/auth.py`** — All auth dependency factories: `jwt_required()`, `apikey_required()`, `apikey_or_jwt_required()`, `get_current_user`, `get_current_user_optional`. JWT creation and validation lives here too.
- **`app/config.py`** — `Settings` via pydantic-settings, loaded from `.env`.
- **`app/models.py`** — SQLAlchemy ORM models: `User`, `Role` (M2M via `user_roles`), `APIKey`, `APIKeyPermission`, `PasswordResetToken`, `RefreshToken`. All share the same `Base`.
- **`app/schemas.py`** — Pydantic v2 schemas for all models.
- **`app/utils.py`** — Password hashing (bcrypt), API key hashing (SHA-256), SendGrid email helper.
- **`app/db/session.py`** — Async SQLAlchemy engine + `AsyncSessionLocal`. `init_db()` calls `create_all` on startup.
- **`app/db/`** — Plain async CRUD functions (no base class); one file per domain (`users.py`, `apikeys.py`, `auth.py`).

### Authentication

Three dependency factories in `app/auth.py`:

| Factory | Header | Enforces |
|---------|--------|----------|
| `jwt_required(required_roles=(...))` | `Authorization: Bearer <token>` | JWT validity + optional role check |
| `apikey_required(route, method)` | `X-API-Key: <key>` | Key active + per-route permission |
| `apikey_or_jwt_required(route, method, required_roles)` | Either | Rejects if both provided |

JWT: access token (15 min) + refresh token in HttpOnly cookie (7 days). API keys are SHA-256 hashed at creation; the raw key is revealed only once (`APIKeyRevealSchema`).

### Adding New Routes

See `app/api/examples.py` — it demonstrates all auth patterns (no auth, JWT, admin-only JWT, API key, either). Use it as a template:

```python
router = APIRouter(prefix="/api/v1/myroutes", tags=["My Feature"])

@router.get("", dependencies=[Depends(apikey_or_jwt_required())])
async def my_endpoint(session: AsyncSession = Depends(get_async_session)):
    ...
```

Then register in `app/main.py`:
```python
from app.api import myroutes
app.include_router(myroutes.router)
```

### Database Backend

Controlled by `DATABASE_URL` in `.env`:
- `sqlite+aiosqlite:///./db.sqlite3` — default/development
- `postgresql+asyncpg://user:pass@host:port/db` — production

**Switching to TimescaleDB:** Replace `app/models.py` with `app/models.py.timescale` and `alembic/env.py` with `alembic/env.py.timescale`. Docker profiles: `timescale-db` or `sqlite-db`.

### API Routes (all prefixed `/api/v1/`)

| Router | Auth | Purpose |
|--------|------|---------|
| `auth` | None/Optional | JWT login, refresh, password reset |
| `apikeys` | JWT | CRUD for API keys and permissions |
| `profile` | JWT | Current user profile and password |
| `users` | None | Username/email availability checks |
| `examples` | Various | Auth pattern reference (not for production) |

### Environment Variables

Key `.env` variables (generated by `setup.sh`):

```
DATABASE_URL=sqlite+aiosqlite:///./db.sqlite3
SECRET_KEY=<auto-generated>
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=Development
FRONTEND_URL=http://localhost:5173
SENDGRID_API_KEY=          # Optional
SENDGRID_FROM_EMAIL=       # Optional
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=admin
```

API docs available at `http://localhost:8000/docs` when running.

## Branching & PR Workflow

This repo is a shared boilerplate/template (`main`) that individual UI projects (e.g. `openrvdas`) branch off of. There are two parallel tracks, mirrored in both `frontend` and `backend`:

```
main                              — shared template baseline
 └─ dev                           — base-improvement integration branch
     └─ issue_NNN                 — base-improvement work → PR → dev

main
 └─ <project> (e.g. openrvdas)    — a project's long-lived branch off main
     └─ <project>_dev (e.g. openrvdas_dev)  — project's integration branch
         └─ issue_NNN              — project-specific work → PR → <project>_dev
```

Issue branches are named `issue_NNN`, where `NNN` is the GitHub issue number zero-padded to 3 digits (e.g. issue #7 → `issue_007`, issue #42 → `issue_042`, issue #123 → `issue_123`).

- **Base/template improvements** (generic, reusable): cut an `issue_NNN` branch from `dev`, PR into `dev`.
- **Project-specific work** (e.g. OpenRVDAS features): cut an `issue_NNN` branch from `<project>_dev` (e.g. `openrvdas_dev`), PR into `<project>_dev`.
- `<project>_dev` merges into `<project>` via PR the same way `dev` merges into `main`.
- Never push issue work directly to `dev`, `<project>_dev`, `main`, or `<project>`.
- All PRs are merged through the GitHub UI (not `git merge`/`gh pr merge` from the CLI).
- Close the linked issue as soon as its PR merges into `dev`/`<project>_dev` — don't wait for the change to reach `main`. GitHub's own `Closes #N` auto-close only fires once the commit lands on the default branch (`main`), and even then isn't fully reliable, so close manually at dev-merge time by default. Exception: leave it open if the issue or PR explicitly says not to close it yet (e.g. it tracks more than just that one PR).
- When `main` gets a new release, open issues to rebase each `<project>` branch and its `<project>_dev` branch against the updated `main`, so projects stay current with base improvements.

See `RELEASING.md` for the step-by-step procedure to cut a release of `main`.
