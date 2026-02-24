import asyncio
import time
from typing import Any, Dict, Optional, Tuple, List
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_openrvdas import LastUpdate

CacheKey = Tuple[Any, ...]


class CachedAsyncCRUDBase:
    """
    Async cache base class for small, semi-static reference data.
    Caches serialized DTOs only. Safe for multi-worker reads.

    Uses a DB-backed LastUpdate timestamp for cross-process invalidation.
    Timestamp checks are throttled to avoid excessive DB hits.
    """

    def __init__(self, check_interval: float = 1.0):
        self._cache: Dict[CacheKey, Any] = {}
        self._lock = asyncio.Lock()

        # Last known DB update timestamp
        self._last_update: Optional[datetime] = None

        # Throttling for DB timestamp checks
        self._last_checked: Optional[float] = None
        self._check_interval = check_interval  # seconds

    # ---------- Low-level cache operations ----------

    async def _get(
        self,
        key: CacheKey,
        session: Optional[AsyncSession] = None
    ) -> Optional[Any]:
        """
        Return cached value or None.

        If `session` is provided, periodically check LastUpdate
        to invalidate stale cache across workers.
        """

        db_ts: Optional[datetime] = None

        # ---- FIX 1 + 2: DB query outside lock + throttled checks ----
        if session:
            now = time.monotonic()

            if (
                self._last_checked is None
                or now - self._last_checked > self._check_interval
            ):
                result = await session.execute(
                    select(LastUpdate.timestamp)
                    .order_by(LastUpdate.timestamp.desc())
                    .limit(1)
                )
                db_ts = result.scalar_one_or_none()

                self._last_checked = now

        # ---- Lock only protects in-memory state ----
        async with self._lock:
            # If DB has a newer timestamp, invalidate cache
            if db_ts and (
                self._last_update is None
                or db_ts > self._last_update
            ):
                self._cache.clear()
                self._last_update = db_ts

            return self._cache.get(key)

    async def _get_by_prefix(
        self,
        prefix: Tuple[Any, ...]
    ) -> List[Any]:
        """
        Return all cached values whose keys start with `prefix`.

        Example:
            prefix = ("config",)

        Matches:

            ("config", "all")
            ("config", "id", 1)
            ("config", "name", "alpha")
        """

        async with self._lock:
            return [
                value
                for key, value in self._cache.items()
                if key[:len(prefix)] == prefix
            ]

    async def _get_items_by_prefix(
        self,
        prefix: Tuple[Any, ...]
    ) -> List[Tuple[CacheKey, Any]]:
        async with self._lock:
            return [
                (key, value)
                for key, value in self._cache.items()
                if key[:len(prefix)] == prefix
            ]


    async def _set(self, key: CacheKey, value: Any) -> None:
        """
        Store a value in cache. Only stores serialized DTOs, no ORM objects.
        """
        async with self._lock:
            self._cache[key] = value

    async def _invalidate(self, *keys: CacheKey) -> None:
        """
        Invalidate specific keys, or entire cache if no keys given.
        """
        async with self._lock:
            if not keys:
                # ---- FIX 3: Reset timestamp on full invalidate ----
                self._cache.clear()
                self._last_update = None
                self._last_checked = None
            else:
                for key in keys:
                    self._cache.pop(key, None)

    async def _invalidate_prefix(self, prefix: Tuple[Any, ...]) -> None:
        """
        Invalidate all keys that start with the given prefix.
        """
        async with self._lock:
            to_delete = [
                k for k in self._cache
                if k[:len(prefix)] == prefix
            ]
            for k in to_delete:
                self._cache.pop(k, None)

    # ---------- Serialization helpers (for subclasses) ----------

    def _serialize(self, obj: Any) -> Any:
        """
        Subclasses override this to convert ORM objects into DTOs.
        """
        raise NotImplementedError

    # ---------- Cache update helpers (for subclasses) ----------

    async def _touch_last_update(self, session: AsyncSession):
        """
        Updates the LastUpdate row so caches know that data has changed.
        """
        result = await session.execute(
            select(LastUpdate).order_by(LastUpdate.timestamp.desc()).limit(1)
        )
        last = result.scalar_one_or_none()

        if last is None:
            last = LastUpdate()
            session.add(last)
        else:
            # if LastUpdate has auto-update timestamp, just touching is enough
            pass
