import copy
from typing import List, Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import selectinload

from app.models_openrvdas import Config, Logger, Mode
from app.db.base import CachedAsyncCRUDBase, CacheKey


class ConfigCRUD(CachedAsyncCRUDBase):
    """CRUD for Config objects with serialized caching.

    Supports:
    - Create, update, delete operations
    - Read operations with optional logger hydration
    - Cached access for full dataset and individual configs
    """

    # ---------- cache keys ----------
    def _key_by_id(self, config_id: str) -> CacheKey:
        return ("config", "id", config_id)

    def _key_all(self) -> CacheKey:
        return ("config", "all")

    # ---------- serialization ----------
    def _serialize(self, config: Config) -> Dict[str, Any]:
        return {
            "id": config.id,
            "logger_id": config.logger_id,
            "mode_ids": [mode.id for mode in getattr(config, "modes", [])],
            "config_json": config.config_json,
            "states": [
                {"id": state.id, "logger_id": state.logger_id, "config_id": state.config_id}
                for state in getattr(config, "states", [])
            ],
        }

    # ---------- read ----------
    async def list_configs(
        self, session: AsyncSession, hydrate_logger: bool = False
    ) -> List[Dict[str, Any]]:
        key = self._key_all()
        cached = await self._get(key, session)
        if cached is not None:
            configs = copy.deepcopy(cached)
        else:
            result = await session.execute(
                select(Config)
                .options(
                    selectinload(Config.logger),
                    selectinload(Config.states),
                    selectinload(Config.modes),
                )
            )
            orm_configs = result.scalars().all()
            configs = [self._serialize(cfg) for cfg in orm_configs]

            # cache full dataset + individual configs
            await self._set(key, configs)
            for cfg in configs:
                await self._set(self._key_by_id(cfg["id"]), cfg)

            configs = copy.deepcopy(configs)

        if hydrate_logger:
            configs = await self.hydrate_configs_loggers(session, configs)

        return configs

    async def get_config(
        self, session: AsyncSession, config_id: str, hydrate_logger: bool = False
    ) -> Dict[str, Any]:
        key = self._key_by_id(config_id)
        cached = await self._get(key, session)
        if cached is not None:
            config = copy.deepcopy(cached)
        else:
            # fallback to full list
            all_configs = await self.list_configs(session)
            config = next((c for c in all_configs if c["id"] == config_id), None)
            if config is None:
                raise NoResultFound(f"Config {config_id} not found")

        if hydrate_logger:
            config = await self.hydrate_config_logger(session, config)

        return config

    async def get_configs_for_mode(
        self, session: AsyncSession, mode_id: str
    ) -> List[Dict[str, Any]]:
        all_configs = await self.list_configs(session)
        return [cfg for cfg in all_configs if mode_id in cfg.get("mode_ids", [])]

    async def get_configs_for_logger(
        self, session: AsyncSession, logger_id: str
    ) -> List[Dict[str, Any]]:
        all_configs = await self.list_configs(session)
        return [cfg for cfg in all_configs if cfg.get("logger_id") == logger_id]

    # ---------- writes ----------
    async def create_config(
        self, session: AsyncSession, return_serialized: bool = True, **data
    ) -> Optional[Dict[str, Any]]:
        config = Config(**data)
        session.add(config)
        await session.flush()

        # reload to ensure relationships are populated if ORM needed
        result = await session.execute(
            select(Config)
            .options(
                selectinload(Config.logger),
                selectinload(Config.states),
                selectinload(Config.modes),
            )
            .where(Config.id == config.id)
        )
        config = result.scalar_one()

        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(config.id), self._serialize(config))

        return self._serialize(config) if return_serialized else config

    async def update_config(
        self,
        session: AsyncSession,
        config_id: str,
        return_serialized: bool = True,
        **data
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(select(Config).where(Config.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise NoResultFound(f"Config {config_id} not found")

        for key, value in data.items():
            if value is not None:
                setattr(config, key, value)

        await session.flush()

        # reload to ensure relationships are populated if ORM needed
        result = await session.execute(
            select(Config)
            .options(
                selectinload(Config.logger),
                selectinload(Config.states),
                selectinload(Config.modes),
            )
            .where(Config.id == config.id)
        )
        config = result.scalar_one()

        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(config.id), self._serialize(config))

        return self._serialize(config) if return_serialized else config

    async def delete_config(
        self, session: AsyncSession, config_id: str, return_serialized: bool = True
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(select(Config).where(Config.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise NoResultFound(f"Config {config_id} not found")

        await session.delete(config)
        await session.flush()

        await self._invalidate(self._key_all())
        await self._invalidate(self._key_by_id(config_id))

        return self._serialize(config) if return_serialized else config


    # ---------- Hydration ----------
    async def hydrate_config_logger(
        self, session: AsyncSession, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich a serialized config dict with full logger info.
        Returns a copy to avoid mutating cached data.
        """
        config_copy = config.copy()
        if "logger_id" in config_copy and config_copy["logger_id"]:
            result = await session.execute(
                select(Logger).where(Logger.id == config_copy["logger_id"])
            )
            logger_obj = result.scalar_one_or_none()
            if logger_obj:
                config_copy["logger"] = {
                    "id": logger_obj.id,
                    "name": logger_obj.name,
                    "type": getattr(logger_obj, "type", None),
                    # Add any other logger fields you want to expose
                }
        return config_copy

    async def hydrate_configs_loggers(
        self, session: AsyncSession, configs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Bulk hydrate logger info for a list of serialized configs.
        """
        return [await self.hydrate_config_logger(session, cfg) for cfg in configs]
