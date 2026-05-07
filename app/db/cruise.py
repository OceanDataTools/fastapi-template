from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.models_openrvdas import Cruise
from app.db.base import CachedAsyncCRUDBase, CacheKey


class CruiseCRUD(CachedAsyncCRUDBase):
    """
    Singleton Cruise record CRUD with serialized caching.
    """

    _cache_key: CacheKey = ("cruise", "singleton")

    # ---------- serialization ----------
    def _serialize_cruise(self, cruise: Cruise) -> Dict[str, Any]:
        return {
            "id": cruise.id,
            "start": cruise.start,
            "end": cruise.end,
            "config_filename": cruise.config_filename,
            "config_mtime_baseline": cruise.config_mtime_baseline,
            "loaded_time": cruise.loaded_time,
        }

    # ---------- read ----------
    async def get_cruise(self, session: AsyncSession) -> Optional[Dict[str, Any]]:
        cached = await self._get(self._cache_key, session)
        if cached is not None:
            return cached

        result = await session.execute(select(Cruise))
        cruise = result.scalars().first()
        if cruise is None:
            return None

        serialized = self._serialize_cruise(cruise)
        await self._set(self._cache_key, serialized)
        return serialized

    # ---------- write ----------
    async def upsert_cruise(
        self,
        session: AsyncSession,
        cruise_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        config_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        if start is not None and end is not None and start > end:
            raise ValueError(f"Cruise start time ({start}) cannot be after end time ({end})")

        result = await session.execute(select(Cruise))
        cruise: Optional[Cruise] = result.scalar_one_or_none()

        if cruise is None:
            cruise = Cruise(
                id=cruise_id,
                start=start,
                end=end,
                config_filename=config_filename,
            )
            session.add(cruise)
        else:
            cruise.id = cruise_id
            if start is not None:
                cruise.start = start
            if end is not None:
                cruise.end = end
            if config_filename is not None:
                cruise.config_filename = config_filename

        await session.flush()

        serialized = self._serialize_cruise(cruise)
        await self._invalidate(self._cache_key)
        return serialized

    async def set_config_mtime_baseline(
        self, session: AsyncSession, mtime: Optional[float]
    ) -> None:
        result = await session.execute(select(Cruise))
        cruise: Optional[Cruise] = result.scalar_one_or_none()
        if cruise is None:
            return
        cruise.config_mtime_baseline = mtime
        await session.flush()
        await self._invalidate(self._cache_key)

    async def delete_cruise(self, session: AsyncSession) -> None:
        result = await session.execute(select(Cruise))
        cruise: Optional[Cruise] = result.scalar_one_or_none()
        if cruise is None:
            raise NoResultFound("No Cruise record found to delete.")

        await session.delete(cruise)
        await session.flush()
        await self._invalidate(self._cache_key)
