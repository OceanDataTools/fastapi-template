from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.base import CachedAsyncCRUDBase, CacheKey
from app.db.configs import ConfigCRUD
from app.models_openrvdas import Config, LoggerConfigState


class LoggerConfigStateCRUD(CachedAsyncCRUDBase):
    """CRUD for LoggerConfigState with serialized caching and optional configuration hydration.

    Supports:
    - Upsert, touch, and delete operations
    - Retrieving states by logger or config
    - Hydrating states with full Config objects
    - Cached latest state per logger
    """

    def __init__(self, config_crud: ConfigCRUD):
        super().__init__()
        self.config_crud = config_crud

    # ---------- cache keys ----------
    def _key_by_id(self, state_id: int) -> CacheKey:
        return ("logger_config_state", "id", state_id)

    def _key_latest_for_logger(self, logger_id: str) -> CacheKey:
        return ("logger_config_state", "latest", logger_id)

    # ---------- serialization ----------
    def _serialize(self, state: LoggerConfigState) -> Dict[str, Any]:
        return {
            "id": state.id,
            "timestamp": state.timestamp,
            "logger_id": state.logger_id,
            "config_id": state.config_id,
            "running": state.running,
            "failed": state.failed,
            "pid": state.pid,
            "errors": state.errors.split("\n") if state.errors else [],
        }

    # ---------- CREATE / UPDATE ----------
    async def upsert_state(
        self,
        session: AsyncSession,
        *,
        config_id: str,
        logger_id: Optional[str] = None,
        running: Optional[bool] = None,
        failed: Optional[bool] = None,
        pid: Optional[int] = None,
        errors: Optional[str] = None,
        return_serialized: bool = True,
    ) -> Optional[Dict[str, Any]]:
        stmt = select(LoggerConfigState).where(
            LoggerConfigState.config_id == config_id,
            LoggerConfigState.logger_id == logger_id,
        )
        result = await session.execute(stmt)
        state = result.scalars().first()

        if state is None:
            state = LoggerConfigState(
                config_id=config_id,
                logger_id=logger_id,
                running=running,
                failed=failed if failed is not None else False,
                pid=pid,
                errors=errors,
            )
            session.add(state)
        else:
            if running is not None:
                state.running = running
            if failed is not None:
                state.failed = failed
            if pid is not None:
                state.pid = pid
            if errors is not None:
                state.errors = errors
            state.timestamp = datetime.now(timezone.utc)

        await session.flush()
        serialized = self._serialize(state)

        if logger_id is not None:
            await self._invalidate(self._key_latest_for_logger(logger_id))
        await self._invalidate(("logger_config_state", "latest"))
        await self._set(self._key_by_id(state.id), serialized)

        return serialized if return_serialized else state

    async def touch_state(
        self, session: AsyncSession, logger_id: str, return_serialized: bool = True
    ) -> Optional[Dict[str, Any]]:
        state = await session.scalar(
            select(LoggerConfigState)
            .where(LoggerConfigState.logger_id == logger_id)
            .order_by(LoggerConfigState.timestamp.desc())
            .limit(1)
        )
        if not state:
            return None

        state.timestamp = datetime.now(timezone.utc)
        await session.flush()

        serialized = self._serialize(state)
        await self._invalidate(self._key_latest_for_logger(logger_id))
        await self._set(self._key_by_id(state.id), serialized)

        return serialized if return_serialized else state

    # ---------- READ ----------
    async def get_state_for_logger(
        self,
        session: AsyncSession,
        logger_id: str,
        since_timestamp: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        hydrate_configs: bool = False,
    ) -> List[Dict[str, Any]]:
        stmt = (
            select(LoggerConfigState)
            .where(LoggerConfigState.logger_id == logger_id)
            .order_by(desc(LoggerConfigState.timestamp))
        )
        if since_timestamp:
            stmt = stmt.where(LoggerConfigState.timestamp >= since_timestamp)
        if limit:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)

        result = await session.execute(stmt)
        states = [self._serialize(s) for s in result.scalars().all()]

        if hydrate_configs:
            states = await self.hydrate_states_configs(session, states)

        return states

    async def get_state_for_config(
        self,
        session: AsyncSession,
        config_id: str,
        since_timestamp: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        hydrate_configs: bool = False,
    ) -> List[Dict[str, Any]]:
        stmt = (
            select(LoggerConfigState)
            .where(LoggerConfigState.config_id == config_id)
            .order_by(desc(LoggerConfigState.timestamp))
        )
        if since_timestamp:
            stmt = stmt.where(LoggerConfigState.timestamp >= since_timestamp)
        if limit:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)

        result = await session.execute(stmt)
        states = [self._serialize(s) for s in result.scalars().all()]

        if hydrate_configs:
            states = await self.hydrate_states_configs(session, states)

        return states

    async def get_latest_status_per_logger(
        self, session: AsyncSession, hydrate_configs: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        cached = await self._get(("logger_config_state", "latest"), session)
        if cached and not hydrate_configs:
            return cached

        subq = (
            select(
                LoggerConfigState.logger_id,
                func.max(LoggerConfigState.timestamp).label("max_ts"),
            )
            .group_by(LoggerConfigState.logger_id)
            .subquery()
        )

        stmt = select(LoggerConfigState).join(
            subq,
            (LoggerConfigState.logger_id == subq.c.logger_id)
            & (LoggerConfigState.timestamp == subq.c.max_ts),
        )

        result = await session.execute(stmt)
        states = result.scalars().all()
        serialized_states = [self._serialize(s) for s in states]

        if hydrate_configs:
            serialized_states = await self.hydrate_states_configs(
                session, serialized_states
            )

        latest_states: Dict[str, Dict[str, Any]] = {}
        for s in serialized_states:
            logger_id = s["logger_id"]
            latest_states[logger_id] = s
            await self._set(self._key_latest_for_logger(logger_id), s)

        await self._set(("logger_config_state", "latest"), latest_states)
        return latest_states

    async def get_status_since_per_logger(
        self,
        session: AsyncSession,
        since_timestamp: datetime,
        hydrate_configs: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        stmt = (
            select(LoggerConfigState)
            .where(LoggerConfigState.timestamp >= since_timestamp)
            .order_by(LoggerConfigState.logger_id, desc(LoggerConfigState.timestamp))
        )
        result = await session.execute(stmt)
        states = result.scalars().all()
        serialized_states = [self._serialize(s) for s in states]

        if hydrate_configs:
            serialized_states = await self.hydrate_states_configs(
                session, serialized_states
            )

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for s in serialized_states:
            grouped.setdefault(s["logger_id"], []).append(s)

        return grouped

    # ---------- DELETE ----------
    async def delete_state(
        self, session: AsyncSession, state_id: int, return_serialized: bool = True
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(
            select(LoggerConfigState).where(LoggerConfigState.id == state_id)
        )
        state = result.scalar_one_or_none()
        if not state:
            raise NoResultFound(f"LoggerConfigState {state_id} not found")

        serialized = self._serialize(state)
        await session.delete(state)
        await session.flush()

        await self._invalidate(self._key_by_id(state.id))
        if state.logger_id:
            await self._invalidate(self._key_latest_for_logger(state.logger_id))

        return serialized if return_serialized else state

    # ---------- hydration ----------
    async def hydrate_states_configs(
        self, session: AsyncSession, states: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not states:
            return []

        config_ids = {s["config_id"] for s in states if s.get("config_id")}
        if not config_ids:
            config_map = {}
        else:
            # Eagerly load modes to avoid async lazy-loading
            result = await session.execute(
                select(Config)
                .where(Config.id.in_(config_ids))
                .options(joinedload(Config.modes), joinedload(Config.states))
            )
            all_configs = result.unique().scalars().all()
            # Now _serialize is fully safe to call
            config_map = {
                cfg.id: self.config_crud._serialize(cfg) for cfg in all_configs
            }

        return [{**s, "config": config_map.get(s["config_id"])} for s in states]

    async def hydrate_state_config(
        self, session: AsyncSession, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        hydrated_list = await self.hydrate_states_configs(session, [state])
        return hydrated_list[0] if hydrated_list else state

    # ---------- HELPERS ----------
    @staticmethod
    def reformat_status_by_timestamp_with_names(
        states: List[Dict[str, Any]]
    ) -> Dict[datetime, Dict[str, Dict[str, Any]]]:
        reformatted: Dict[datetime, Dict[str, Dict[str, Any]]] = {}
        for state in states:
            ts = state["timestamp"]
            reformatted.setdefault(ts, {})[state["logger_id"]] = {
                "config": state["config_id"],
                "running": state["running"],
                "failed": state["failed"],
                "pid": state["pid"],
                "errors": state["errors"],
            }
        return reformatted
