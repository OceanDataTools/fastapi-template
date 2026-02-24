import copy
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import selectinload, joinedload

from app.models_openrvdas import Mode, Config
from app.db.base import CachedAsyncCRUDBase, CacheKey
from app.db.configs import ConfigCRUD
from app.db.loggers import LoggerCRUD


class ModeCRUD(CachedAsyncCRUDBase):
    """CRUD for Mode objects with serialized caching.

    Supports:
    - Create, update, delete operations
    - Read operations with optional config hydration
    - Bulk hydration for configs and loggers
    """

    def __init__(self, config_crud: ConfigCRUD, logger_crud: LoggerCRUD):
        super().__init__()
        self.config_crud = config_crud
        self.logger_crud = logger_crud

    # ---------- cache keys ----------

    def _key_by_id(self, mode_id: str) -> CacheKey:
        return ("mode", "id", mode_id)

    def _key_all(self) -> CacheKey:
        return ("mode", "all")

    def _key_active(self) -> CacheKey:
        return ("mode", "active")

    def _key_default(self) -> CacheKey:
        return ("mode", "default")

    # ---------- Serialization ----------

    def _serialize(self, mode: Mode) -> dict:
        return {
            "id": mode.id,
            "active": mode.active,
            "default": mode.default,
            "configs": [
                {"id": cfg.id, "logger_id": cfg.logger_id}
                for cfg in mode.configs
            ],
        }

    # ---------- Reads ----------

    async def list_modes(
        self,
        session: AsyncSession,
        hydrate_configs: bool = False,
    ) -> List[dict]:
        key = self._key_all()
        cached = await self._get(key, session)

        if cached is not None:
            modes = copy.deepcopy(cached)
        else:
            result = await session.execute(
                select(Mode).options(
                    selectinload(Mode.configs)
                )
            )
            orm_modes = result.scalars().all()
            modes = [self._serialize(m) for m in orm_modes]

            serialized = [self._serialize(m) for m in orm_modes]

            await self._set(key, copy.deepcopy(serialized))

            for mode in serialized:
                await self._set(self._key_by_id(mode["id"]), copy.deepcopy(mode))

            modes = copy.deepcopy(serialized)

        if hydrate_configs:
            modes = await self.hydrate_modes_configs(session, modes)

        return modes

    async def get_mode(
        self,
        session: AsyncSession,
        mode_id: str,
        hydrate_configs: bool = False,
    ) -> Optional[Dict[str, Any]]:
        key = self._key_by_id(mode_id)
        cached = await self._get(key, session)

        if cached is not None:
            mode = copy.deepcopy(cached)
        else:
            all_modes = await self.list_modes(session)
            mode = next((m for m in all_modes if m["id"] == mode_id), None)
            if mode is None:
                raise NoResultFound(f"Mode {mode_id} not found")

        if hydrate_configs:
            mode = await self.hydrate_mode_configs(session, mode)

        return mode

    async def get_active_mode(
        self,
        session: AsyncSession,
        hydrate_configs: bool = False,
    ) -> Optional[Dict[str, Any]]:
        cached = await self._get(self._key_active(), session)

        if cached is not None:
            mode = copy.deepcopy(cached)
        else:
            all_modes = await self.list_modes(session)
            mode = next((m for m in all_modes if m["active"]), None)
            if mode is None:
                raise NoResultFound(f"Active mode not found")

            await self._set(self._key_active(), copy.deepcopy(mode))

        if hydrate_configs:
            mode = await self.hydrate_mode_configs(session, mode)

        return mode

    async def get_default_mode(
        self,
        session: AsyncSession,
        hydrate_configs: bool = False,
    ) -> Optional[Dict[str, Any]]:
        cached = await self._get(self._key_default(), session)

        if cached is not None:
            mode = copy.deepcopy(cached)
        else:
            all_modes = await self.list_modes(session)
            mode = next((m for m in all_modes if m["default"]), None)
            if mode is None:
                raise NoResultFound(f"Default mode not found")

            await self._set(self._key_default(), copy.deepcopy(mode))


        if hydrate_configs:
            mode = await self.hydrate_mode_configs(session, mode)

        return mode

    # ---------- Writes ----------

    async def create_mode(
        self,
        session: AsyncSession,
        return_serialized: bool = True,  # optional flag
        **data,
    ) -> Optional[Dict[str, Any]]:
        mode = Mode(**data)
        session.add(mode)
        await session.flush()

        serialized = self._serialize(mode)

        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(mode.id), copy.deepcopy(serialized))

        return serialized if return_serialized else mode

    async def update_mode(
        self,
        session: AsyncSession,
        mode_id: str,
        return_serialized: bool = True,  # optional flag
        **data,
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(
            select(Mode)
            .options(selectinload(Mode.configs))
            .where(Mode.id == mode_id)
        )
        mode = result.scalar_one_or_none()
        if not mode:
            raise NoResultFound(f"Mode {mode_id} not found")

        default = data.get("default")
        if default is True:

            # Clear existing default mode
            result = await session.execute(
                select(Mode).where(Mode.default.is_(True))
            )
            prev_default_mode = result.scalar_one_or_none()
            if prev_default_mode:
                prev_default_mode.default = False
                await self._invalidate(self._key_by_id(prev_default_mode.id), self._key_default())

        for key, value in data.items():
            if key not in ("config_ids",) and value is not None:
                setattr(mode, key, value)

        config_ids = data.get("config_ids")
        if config_ids is not None:
            configs = await self.config_crud.get_configs_by_ids(session, config_ids)
            mode.configs = configs

        await session.flush()

        result = await session.execute(
            select(Mode)
            .options(selectinload(Mode.configs))
            .where(Mode.id == mode_id)
        )
        mode = result.scalar_one()

        serialized = self._serialize(mode)
        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(mode.id), copy.deepcopy(serialized))

        if default is True:
            await self._set(self._key_default(), copy.deepcopy(serialized))

        return serialized if return_serialized else mode

    async def delete_mode(
        self,
        session: AsyncSession,
        mode_id: str,
        return_serialized: bool = True,
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(
            select(Mode)
            .options(selectinload(Mode.configs))
            .where(Mode.id == mode_id)
        )

        mode = result.scalar_one_or_none()
        if not mode:
            raise NoResultFound(f"Mode {mode_id} not found")

        await session.delete(mode)
        await session.flush()

        await self._invalidate(self._key_all(), self._key_by_id(mode_id))
        if mode.default:
            await self._invalidate(self._key_default())
        if mode.active:
            await self._invalidate(self._key_active())

        return self._serialize(mode) if return_serialized else mode

    async def set_active_mode(
        self,
        session: AsyncSession,
        mode_id: str,
        return_serialized: bool = True,  # optional flag
    ) -> Optional[Dict[str, Any]]:

        # Clear existing active mode
        result = await session.execute(
            select(Mode).where(Mode.active.is_(True))
        )
        prev_active_mode = result.scalar_one_or_none()
        if prev_active_mode:
            prev_active_mode.active = False
            await self._invalidate(self._key_by_id(prev_active_mode.id), self._key_active())

        result = await session.execute(
            select(Mode)
            .options(selectinload(Mode.configs))
            .where(Mode.id == mode_id)
        )
        mode = result.scalar_one_or_none()
        if not mode:
            raise NoResultFound(f"Mode {mode_id} not found")

        mode.active = True

        await session.flush()

        result = await session.execute(
            select(Mode)
            .options(selectinload(Mode.configs))
            .where(Mode.id == mode_id)
        )
        mode = result.scalar_one()

        serialized = self._serialize(mode)
        await self._invalidate(self._key_all())
        await self._set(self._key_by_id(mode.id), copy.deepcopy(serialized),)
        await self._set(self._key_active(), copy.deepcopy(serialized),)

        return serialized if return_serialized else mode

    # ---------- Hydration ----------

    # async def hydrate_mode_configs(
    #     self,
    #     session: AsyncSession,
    #     mode: dict,
    # ) -> List[dict]:
    #     all_configs = await self.config_crud.list_configs(session)

    #     config_map = {c["id"]: c for c in all_configs}

    #     configs = []
    #     for cfg_ref in mode["configs"]:
    #         cfg = config_map.get(cfg_ref["id"])
    #         if cfg:
    #             logger = await self.logger_crud.get_logger(session, cfg["logger_id"])
    #             cfg_copy = copy.deepcopy(cfg)
    #             cfg_copy["logger"] = logger
    #             configs.append(cfg_copy)

    #     return configs

    async def hydrate_modes_configs(
        self,
        session: AsyncSession,
        modes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        if not modes:
            return []

        config_ids = {
            cfg["id"]
            for m in modes
            for cfg in m.get("configs", [])
        }

        config_map = {}

        if config_ids:
            result = await session.execute(
                select(Config)
                .where(Config.id.in_(config_ids))
                .options(
                    joinedload(Config.modes),
                    joinedload(Config.states)
                )
            )

            all_configs = result.unique().scalars().all()

            config_map = {
                cfg.id: self.config_crud._serialize(cfg)
                for cfg in all_configs
            }

        hydrated_modes = []

        for mode in modes:
            mode_copy = copy.deepcopy(mode)

            mode_copy["configs"] = [
                config_map[cfg["id"]]
                for cfg in mode.get("configs", [])
                if cfg["id"] in config_map
            ]

            hydrated_modes.append(mode_copy)

        return hydrated_modes



    async def hydrate_mode_configs(
        self,
        session: AsyncSession,
        mode: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Hydrate a single mode using the batch hydrate function.
        """
        hydrated_list = await self.hydrate_modes_configs(session, [mode])
        return hydrated_list[0] if hydrated_list else mode
