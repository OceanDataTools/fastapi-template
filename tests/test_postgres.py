"""PostgreSQL-only checks. Skipped unless TEST_DATABASE_URL is set."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from app.models import APIKey, Base, User

pytestmark = pytest.mark.postgres


async def test_migrations_match_models(db_session):
    """Schema built by `alembic upgrade head` must match app/models.py."""

    def _diff(sync_conn):
        ctx = MigrationContext.configure(sync_conn)
        return compare_metadata(ctx, Base.metadata)

    conn = await db_session.connection()
    diff = await conn.run_sync(_diff)
    assert diff == [], f"models and migrations have diverged: {diff}"


async def test_timestamptz_round_trip(db_session):
    """Aware datetimes keep their instant (and come back aware) on timestamptz."""
    admin = await db_session.scalar(select(User).where(User.username == "admin"))
    expires = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-7)))
    key = APIKey(user_id=admin.id, key_hash=uuid4().hex, expires_at=expires)
    db_session.add(key)
    await db_session.commit()
    key_id = key.id
    db_session.expunge_all()

    stored = await db_session.get(APIKey, key_id)
    assert stored.expires_at.tzinfo is not None
    assert stored.expires_at == expires
    assert stored.created_at.tzinfo is not None

    await db_session.delete(stored)
    await db_session.commit()
