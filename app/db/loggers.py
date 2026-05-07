import copy
from typing import List, Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import selectinload, joinedload

from app.models_openrvdas import Logger, Config
from app.db.base import CachedAsyncCRUDBase, CacheKey
from app.db.configs import ConfigCRUD


class LoggerCRUD(CachedAsyncCRUDBase):
    """CRUD for Logger objects with serialized caching.

    Supports:
    - Create, update, delete operations
    - Read operations with optional config hydration
    - Bulk hydration for multiple loggers
    """

    def __init__(self, config_crud: ConfigCRUD):
        super().__init__()
        self.config_crud = config_crud

    # ---------- cache keys ----------

    def _key_by_id(self, logger_id: str) -> CacheKey:
        return ("logger", "id", logger_id)

    def _key_all(self) -> CacheKey:
        return ("logger", "all")

    # ---------- serialization ----------

    def _serialize(self, logger: Logger) -> Dict[str, Any]:
        states = getattr(logger, "config_states", [])
        latest = max(states, key=lambda s: s.timestamp) if states else None
        return {
            "id": logger.id,
            "configs": [{"id": cfg.id} for cfg in getattr(logger, "configs", [])],
            "active_config": latest.config_id if latest else None,
            "running": bool(latest.running) if latest else False,
        }

    # ---------- read ----------

    async def list_loggers(
        self,
        session: AsyncSession,
        hydrate_configs: bool = False,
    ) -> List[Dict[str, Any]]:
        key = self._key_all()
        cached = await self._get(key, session)

        if cached is not None:
            loggers = copy.deepcopy(cached)
        else:
            result = await session.execute(
                select(Logger).options(
                    selectinload(Logger.configs),
                    selectinload(Logger.config_states),
                )
            )
            orm_loggers = result.scalars().all()
            loggers = [self._serialize(l) for l in orm_loggers]

            # cache
            await self._set(key, copy.deepcopy(loggers))
            for logger in loggers:
                await self._set(self._key_by_id(logger["id"]), copy.deepcopy(logger))

            loggers = copy.deepcopy(loggers)

        if hydrate_configs:
            loggers = await self.hydrate_loggers_configs(session, loggers)

        return loggers

    async def get_logger(
        self,
        session: AsyncSession,
        logger_id: str,
        hydrate_configs: bool = False,
    ) -> Dict[str, Any]:
        key = self._key_by_id(logger_id)
        cached = await self._get(key, session)

        if cached is not None:
            logger = copy.deepcopy(cached)
        else:
            all_loggers = await self.list_loggers(session)
            logger = next((l for l in all_loggers if l["id"] == logger_id), None)
            if logger is None:
                raise NoResultFound(f"Logger {logger_id} not found")

        if hydrate_configs:
            logger = await self.hydrate_logger_configs(session, logger)

        return logger

    # ---------- writes ----------

    async def create_logger(
        self,
        session: AsyncSession,
        return_serialized: bool = True,
        **data,
    ) -> Optional[Dict[str, Any]]:
        logger = Logger(**data)
        session.add(logger)
        await session.flush()

        result = await session.execute(
            select(Logger)
            .options(
                selectinload(Logger.configs),
                selectinload(Logger.config_states),
            )
            .where(Logger.id == logger.id)
        )
        logger = result.scalar_one()

        serialized = self._serialize(logger)

        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(logger.id), serialized)

        return serialized if return_serialized else logger

    async def update_logger(
        self,
        session: AsyncSession,
        logger_id: str,
        return_serialized: bool = True,
        **data,
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(
            select(Logger)
            .options(
                selectinload(Logger.configs),
                selectinload(Logger.config_states)
            )
            .where(Logger.id == logger_id)
        )
        logger = result.scalar_one_or_none()
        if not logger:
            raise NoResultFound(f"Logger {logger_id} not found")

        for key, value in data.items():
            if value is not None:
                setattr(logger, key, value)

        await session.flush()

        # reload to ensure relationships are populated if ORM needed
        result = await session.execute(
            select(Logger)
            .options(
                selectinload(Logger.configs),
                selectinload(Logger.config_states)
            )
            .where(Logger.id == logger_id)
        )
        logger = result.scalar_one()

        serialized = self._serialize(logger)
        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(logger.id), serialized)

        return serialized if return_serialized else logger

    async def delete_logger(
        self,
        session: AsyncSession,
        logger_id: str,
        return_serialized: bool = True,
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(
            select(Logger)
            .options(
                selectinload(Logger.configs),
                selectinload(Logger.config_states)
            )
            .where(Logger.id == logger_id)
        )
        logger = result.scalar_one_or_none()
        if not logger:
            raise NoResultFound(f"Logger {logger_id} not found")

        serialized = self._serialize(logger)

        await session.delete(logger)
        await session.flush()

        await self._invalidate(self._key_all(), self._key_by_id(logger_id))

        return serialized if return_serialized else logger

    # ---------- config assignment ----------

    async def upsert_config_for_logger(
        self,
        session: AsyncSession,
        logger_id: str,
        config_id: str,
    ) -> None:
        result = await session.execute(
            select(Logger)
            .options(selectinload(Logger.configs), selectinload(Logger.config_states))
            .where(Logger.id == logger_id)
        )
        logger = result.scalar_one_or_none()
        if not logger:
            raise NoResultFound(f"Logger {logger_id} not found")

        result = await session.execute(select(Config).where(Config.id == config_id))
        cfg = result.scalar_one_or_none()
        if not cfg:
            raise NoResultFound(f"Config {config_id} not found")

        cfg.logger_id = logger.id
        await session.flush()

        await self._invalidate(self._key_all(), self._key_by_id(logger_id))

    # ---------- optimized hydration ----------

    async def hydrate_loggers_configs(
        self,
        session: AsyncSession,
        loggers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Hydrate multiple loggers with their full config objects in a single query.
        """
        if not loggers:
            return []

        # Gather all unique config IDs
        config_ids = {c["id"] for l in loggers for c in l.get("configs", [])}

        config_map = {}
        if config_ids:
            # Eagerly load modes to avoid async lazy-loading
            result = await session.execute(
                select(Config)
                .where(Config.id.in_(config_ids))
                .options(
                    joinedload(Config.modes),
                    joinedload(Config.states)
                )
            )
            all_configs = result.unique().scalars().all()
            # _serialize is synchronous, so NO await
            config_map = {cfg.id: self.config_crud._serialize(cfg) for cfg in all_configs}

        hydrated_loggers = []
        for logger in loggers:
            logger_copy = copy.deepcopy(logger)
            logger_copy["configs"] = [
                config_map[c["id"]] for c in logger.get("configs", []) if c["id"] in config_map
            ]
            hydrated_loggers.append(logger_copy)

        return hydrated_loggers


    async def hydrate_logger_configs(
        self,
        session: AsyncSession,
        logger: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Hydrate a single logger using the batch hydrate function.
        """
        hydrated_list = await self.hydrate_loggers_configs(session, [logger])
        return hydrated_list[0] if hydrated_list else logger

