from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import CachedAsyncCRUDBase, CacheKey
from app.models_openrvdas import LogMessage


class LogMessageCRUD(CachedAsyncCRUDBase):
    """
    CRUD for LogMessage using serialized caching for individual logs and latest N logs.
    Flexible queries are not cached.
    """

    # ---------- cache keys ----------
    def _key_by_id(self, log_id: int) -> CacheKey:
        return ("log_message", "id", log_id)

    def _key_latest(self, limit: int) -> CacheKey:
        return ("log_message", "latest", limit)

    # ---------- serialization ----------
    def _serialize_log(self, log: LogMessage) -> Dict[str, Any]:
        return {
            "id": log.id,
            "timestamp": log.timestamp,
            "source": log.source,
            "user": log.user,
            "log_level": log.log_level,
            "message": log.message,
        }

    # ---------- read ----------
    async def get_log_message(
        self, session: AsyncSession, log_id: int
    ) -> Optional[Dict[str, Any]]:
        key = self._key_by_id(log_id)
        cached = await self._get(key, session)
        if cached is not None:
            return cached

        result = await session.execute(
            select(LogMessage).where(LogMessage.id == log_id)
        )
        log = result.scalar_one_or_none()
        if log is None:
            return None

        serialized = self._serialize_log(log)
        await self._set(key, serialized)
        return serialized

    async def get_latest_logs(
        self, session: AsyncSession, limit: int = 100
    ) -> List[Dict[str, Any]]:
        key = self._key_latest(limit)
        cached = await self._get(key, session)
        if cached is not None:
            return cached

        result = await session.execute(
            select(LogMessage).order_by(LogMessage.timestamp.desc()).limit(limit)
        )
        logs = result.scalars().all()
        serialized = [self._serialize_log(log) for log in logs]

        await self._set(key, serialized)
        for log in logs:
            await self._set(self._key_by_id(log.id), self._serialize_log(log))

        return serialized

    async def get_log_messages(
        self,
        session: AsyncSession,
        source: Optional[str] = None,
        user: Optional[str] = None,
        log_level: Optional[int] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Flexible filtered query. Not cached to avoid unbounded key explosion.
        """
        stmt = select(LogMessage)
        if source is not None:
            stmt = stmt.where(LogMessage.source == source)
        if user is not None:
            stmt = stmt.where(LogMessage.user == user)
        if log_level is not None:
            stmt = stmt.where(LogMessage.log_level == log_level)
        if since is not None:
            stmt = stmt.where(LogMessage.timestamp >= since)
        if until is not None:
            stmt = stmt.where(LogMessage.timestamp <= until)
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt.order_by(LogMessage.timestamp.desc()))
        logs = result.scalars().all()
        return [self._serialize_log(log) for log in logs]

    # ---------- write ----------
    async def create_log_message(
        self,
        session: AsyncSession,
        source: Optional[str] = None,
        user: Optional[str] = None,
        log_level: Optional[int] = 0,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        log = LogMessage(
            source=source,
            user=user,
            log_level=log_level,
            message=message,
        )
        session.add(log)
        await session.flush()

        serialized = self._serialize_log(log)

        # Invalidate latest caches
        await self._invalidate_prefix(("log_message",))
        await self._set(self._key_by_id(log.id), serialized)

        return serialized

    async def delete_log_message(self, session: AsyncSession, log_id: int) -> None:
        result = await session.execute(
            select(LogMessage).where(LogMessage.id == log_id)
        )
        log = result.scalar_one_or_none()
        if log is None:
            raise NoResultFound(f"No LogMessage found with id={log_id}")

        await session.delete(log)
        await session.flush()

        await self._invalidate(self._key_by_id(log_id))
        await self._invalidate_prefix(("log_message",))

    async def delete_all_log_messages(self, session: AsyncSession) -> int:
        result = await session.execute(select(LogMessage))
        logs = result.scalars().all()
        if not logs:
            raise NoResultFound("No LogMessage records found to delete.")

        count = len(logs)
        for log in logs:
            await session.delete(log)

        await session.flush()
        # Invalidate all cached logs
        await self._invalidate_prefix(("log_message",))
        return count
