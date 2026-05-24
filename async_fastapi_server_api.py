#!/usr/bin/env python3
"""
API for interacting with the OpenRVDAS data store using updated CRUDs.
"""

import logging
import sys
import json
from typing import Any, Dict, List, Optional
from os.path import dirname, realpath
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import NoResultFound

sys.path.append(dirname(dirname(realpath(__file__))))
try:
    from logger.utils.timestamp import datetime_obj, DATE_FORMAT  # noqa: E402
except ImportError:
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"  # type: ignore[assignment]

    def datetime_obj(timestring: Any, time_format: str = DATE_FORMAT) -> Optional[datetime]:  # type: ignore[misc]
        try:
            return datetime.strptime(timestring, time_format)
        except Exception:
            return None

sys.path.append(dirname(realpath(__file__)))
from app.db.session import AsyncSessionLocal
from app.db.locks import sqlite_write_lock
from app.db import (
    config_crud as crud_configs,
    cruise_crud as crud_cruise,
    log_message_crud as crud_log_messages,
    logger_config_state_crud as crud_logger_config_state,
    logger_crud as crud_loggers,
    mode_crud as crud_modes,
)
from app.models_openrvdas import LastUpdate


################################################################################
class AsyncFastAPIServerAPI:
    """API for interacting with OpenRVDAS data store."""

    ############################################################################
    # ------------------- Internal session helpers ----------------------------#
    ############################################################################

    async def _with_session(self, func, *args, **kwargs):
        """Helper to manage a single session for a function."""
        async with AsyncSessionLocal() as session:
            return await func(session, *args, **kwargs)

    async def _with_transaction(self, func, *args, **kwargs):
        """Helper to manage a single session and wrap writes in a transaction."""
        async with sqlite_write_lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    result = await func(session, *args, **kwargs)
                return result

    ############################################################################
    # -------------------------- Update helpers --------------------------------
    ############################################################################

    async def _touch_last_update(self, session):
        result = await session.execute(
            select(LastUpdate).order_by(LastUpdate.timestamp.desc()).limit(1)
        )
        last = result.scalar_one_or_none()
        if last is None:
            last = LastUpdate()
            session.add(last)
        else:
            last.timestamp = func.now()
        await session.flush()
        await session.refresh(last)
        return last

    ############################################################################
    # -------------------------- Read Methods ---------------------------------
    ############################################################################

    async def get_configuration(self):
        async def _inner(session):
            cruise = await crud_cruise.get_cruise(session)
            active_mode = await crud_modes.get_active_mode(session, hydrate_configs=True)
            default_mode = await crud_modes.get_default_mode(session, hydrate_configs=True)
            modes = await crud_modes.list_modes(session, hydrate_configs=True)
            loggers = await crud_loggers.list_loggers(session, hydrate_configs=True)

            return {
                "id": cruise["id"] if cruise else None,
                "start": datetime.strftime(cruise["start"], DATE_FORMAT) if cruise else None,
                "end": datetime.strftime(cruise["end"], DATE_FORMAT) if cruise else None,
                "config_filename": cruise.get("config_filename") if cruise else None,
                "loaded_time": cruise.get("loaded_time") if cruise else None,
                "active_mode": active_mode["id"] if active_mode else None,
                "default_mode": default_mode["id"] if default_mode else None,
                "modes": modes,
                "loggers": loggers,
            }

        return await self._with_session(_inner)

    async def get_modes(self, hydrate_configs: bool = True):
        async def _inner(session):
            return await crud_modes.list_modes(session, hydrate_configs=hydrate_configs)
        return await self._with_session(_inner)

    async def get_active_mode(self, hydrate_configs: bool = True):
        async def _inner(session):
            mode = await crud_modes.get_active_mode(session, hydrate_configs=hydrate_configs)
            return mode.get("id") if mode else None
        return await self._with_session(_inner)

    async def get_default_mode(self, hydrate_configs: bool = True):
        async def _inner(session):
            mode = await crud_modes.get_default_mode(session, hydrate_configs=hydrate_configs)
            return mode.get("id") if mode else None
        return await self._with_session(_inner)

    async def get_loggers(self):
        async def _inner(session):
            loggers = await crud_loggers.list_loggers(session, hydrate_configs=True)
            return {
                logger.get("id"): {
                    "configs": {cfg.get("id"): cfg for cfg in logger.get("configs", [])}
                }
                for logger in loggers if logger.get("id")
            }
        return await self._with_session(_inner)

    async def get_logger(self, logger_id: str):
        async def _inner(session):
            logger = await crud_loggers.get_logger(session, logger_id, hydrate_configs=True)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")
            return {"configs": {cfg.get("id"): cfg for cfg in logger.get("configs", [])}}
        return await self._with_session(_inner)

    async def get_logger_config(self, config_id: str):
        async def _inner(session):
            cfg = await crud_configs.get_config(session, config_id)
            if not cfg:
                raise KeyError(f"Config {config_id} not found")
            return cfg.get("config_json")
        return await self._with_session(_inner)

    async def get_logger_configs(self, mode_id: Optional[str] = None):
        async def _inner(session):
            if mode_id is None:
                # Return the currently desired config per logger from LoggerConfigState,
                # which is what set_active_logger_config and set_active_mode write to.
                latest_states = await crud_logger_config_state.get_latest_status_per_logger(session)
                if not latest_states:
                    return None
                result = {}
                for logger_id, state in latest_states.items():
                    config_id = state.get("config_id")
                    if config_id:
                        cfg = await crud_configs.get_config(session, config_id)
                        if cfg:
                            config_dict = json.loads(cfg.get("config_json") or "{}")
                            config_dict["name"] = config_id
                            result[logger_id] = config_dict
                return result if result else None
            else:
                mode = await crud_modes.get_mode(session, mode_id, hydrate_configs=True)
                if not mode:
                    raise KeyError(f"Mode {mode_id} not found")
                return {
                    cfg.get("logger_id"): {
                        "name": cfg.get("id"),
                        "config_json": cfg.get("config_json"),
                        "logger": cfg.get("logger")
                    }
                    for cfg in mode.get("configs", [])
                }
        return await self._with_session(_inner)

    async def get_logger_config_name(self, logger_id: str, mode_id: Optional[str] = None):
        async def _inner(session):
            if mode_id is None:
                mode = await crud_modes.get_active_mode(session, hydrate_configs=True)
            else:
                mode = await crud_modes.get_mode(session, mode_id, hydrate_configs=True)
            logger = await crud_loggers.get_logger(session, logger_id, hydrate_configs=True)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")
            for cfg in mode.get("configs", []):
                if cfg.get("logger_id") == logger.get("id"):
                    return cfg.get("id")
            raise KeyError(f"No Config for logger {logger_id} in mode {mode.get('id')}")
        return await self._with_session(_inner)

    async def get_logger_config_names(self, logger_id: str):
        async def _inner(session):
            logger = await crud_loggers.get_logger(session, logger_id, hydrate_configs=True)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")
            configs = await crud_configs.get_configs_for_logger(session, logger.get("id"))
            return [cfg.get("id") for cfg in configs] if configs else []
        return await self._with_session(_inner)

    async def get_status(self, since_timestamp: Optional[datetime] = None):
        async def _inner(session):
            if since_timestamp is None:
                # Returns {logger_id: single_state_dict}
                states = await crud_logger_config_state.get_latest_status_per_logger(session)
                flat = list(states.values())
            else:
                # Returns {logger_id: [list_of_state_dicts]}
                states = await crud_logger_config_state.get_status_since_per_logger(session, since_timestamp)
                flat = [s for states_list in states.values() for s in states_list]
            return await crud_logger_config_state.reformat_status_by_timestamp_with_names(flat)
        return await self._with_session(_inner)

    async def get_message_log(self, source=None, user=None, log_level=sys.maxsize, since_timestamp=None):
        async def _inner(session):
            log_messages = await crud_log_messages.get_log_messages(
                session, source=source, user=user, log_level=log_level, since_timestamp=since_timestamp
            )
            return [
                (m.timestamp.timestamp(), m.source, m.user, m.log_level, m.message)
                for m in log_messages
            ]
        return await self._with_session(_inner)

    ############################################################################
    # -------------------------- Write Methods --------------------------------
    ############################################################################

    async def message_log(self, source, user, log_level, message):
        async def _inner(session):
            log = await crud_log_messages.create_log_message(
                session, source=source, user=user, log_level=log_level, message=message
            )
            logging.warning(log)
        await self._with_transaction(_inner)

    async def update_status(self, status: Dict[str, Dict[str, Any]]):
        async def _inner(session):
            for logger_id, logger_report in status.items():
                config_id = logger_report.get("config")
                error_text = "\n".join(logger_report.get("errors") or []) or None
                await crud_logger_config_state.upsert_state(
                    session,
                    config_id=config_id,
                    logger_id=logger_id,
                    running=logger_report.get("running"),
                    failed=logger_report.get("failed"),
                    pid=logger_report.get("pid"),
                    errors=error_text,
                    update_timestamp=False,
                )
        await self._with_transaction(_inner)

    async def set_active_mode(self, mode_id: str):
        async def _inner(session):
            # Get ORM object from CRUD
            mode_obj = await crud_modes.set_active_mode(session, mode_id, return_serialized=False)

            # Now this is safe — iterate ORM relationships
            for cfg in mode_obj.configs:
                await crud_logger_config_state.upsert_state(
                    session,
                    config_id=cfg.id,
                    logger_id=cfg.logger_id,
                    running=False,
                    pid=0,
                )
            await self._touch_last_update(session)
        await self._with_transaction(_inner)

    async def set_active_logger_config(self, logger_id: str, config_id: str):
        async def _inner(session):
            state = await crud_logger_config_state.upsert_state(
                session, config_id=config_id, logger_id=logger_id, running=False, pid=0
            )
            await self._touch_last_update(session)
            return state
        return await self._with_transaction(_inner)

    async def load_configuration(self, configuration: Dict[str, Any], preserve_mode: bool = False):
        cruise_cfg = configuration.get("cruise", {})
        loggers_cfg = configuration.get("loggers")
        modes_cfg = configuration.get("modes")
        default_mode_id = configuration.get("default_mode")
        configs_cfg = configuration.get("configs")

        if loggers_cfg is None or modes_cfg is None or configs_cfg is None:
            raise ValueError("Configuration must define loggers, modes, and configs")

        # Sanity validation
        for cfg_id, cfg in configs_cfg.items():
            if cfg is None:
                raise ValueError(f"No logger for config '{cfg_id}'")

        async def _inner(session):
            # 0. Clear existing modes / loggers / configs so re-loading the same
            #    (or a different) cruise definition doesn't hit UNIQUE violations.
            for mode in await crud_modes.list_modes(session):
                await crud_modes.delete_mode(session, mode["id"])
            for logger in await crud_loggers.list_loggers(session):
                await crud_loggers.delete_logger(session, logger["id"])
            for cfg in await crud_configs.list_configs(session):
                await crud_configs.delete_config(session, cfg["id"])

            # 1. Cruise
            cruise = await crud_cruise.upsert_cruise(
                session,
                cruise_id=cruise_cfg.get("id", "Cruise"),
                start=datetime_obj(cruise_cfg.get("start"), time_format=DATE_FORMAT) if cruise_cfg.get("start") else None,
                end=datetime_obj(cruise_cfg.get("end"), time_format=DATE_FORMAT) if cruise_cfg.get("end") else None,
                config_filename=cruise_cfg.get("config_filename")
            )

            # 2. Loggers
            logger_objs = {
                logger_id: await crud_loggers.create_logger(session, id=logger_id)
                for logger_id in loggers_cfg.keys()
            }

            # 3. Configs
            logger_config_objs = {
                config_id: await crud_configs.create_config(
                    session,
                    id=config_id,
                    config_json=json.dumps(cfg_body),
                )
                for config_id, cfg_body in configs_cfg.items()
            }

            # 4. Logger ↔ LoggerConfig
            for logger_id, logger_info in loggers_cfg.items():
                for config_id in logger_info["configs"]:
                    await crud_loggers.upsert_config_for_logger(
                        session=session, logger_id=logger_id, config_id=config_id
                    )

            # 5. Modes
            for mode_id in modes_cfg.keys():
                await crud_modes.create_mode(session, id=mode_id)

            # 6. Mode ↔ Logger ↔ LoggerConfig
            for mode_name, logger_map in modes_cfg.items():
                for logger_name, config_name in logger_map.items():
                    await crud_modes.upsert_config_for_mode(
                        session=session,
                        mode_id=mode_name,
                        config_id=config_name,
                    )

            # 7. Default / Active Mode
            if default_mode_id:
                await crud_modes.set_default_mode(session, default_mode_id)
            if not preserve_mode:
                await crud_modes.set_active_mode(session, default_mode_id)

            await self._touch_last_update(session)

        await self._with_transaction(_inner)

    async def delete_configuration(self):
        async def _inner(session):
            try:
                await crud_cruise.delete_cruise(session)
                for mode in await crud_modes.list_modes(session):
                    await crud_modes.delete_mode(session, mode["id"])
                for logger in await crud_loggers.list_loggers(session):
                    await crud_loggers.delete_logger(session, logger["id"])
                for cfg in await crud_configs.list_configs(session):
                    await crud_configs.delete_config(session, cfg["id"])
            except Exception:
                logging.exception("Failed to delete configuration")
                raise
            await self._touch_last_update(session)

        await self._with_transaction(_inner)
