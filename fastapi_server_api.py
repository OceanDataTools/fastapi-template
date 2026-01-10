#!/usr/bin/env python3
"""
API for interacting with data store. Implementations should subclass.
"""
import logging
import sys
from os.path import dirname, realpath

sys.path.append(dirname(dirname(realpath(__file__))))
from logger.utils.timestamp import datetime_obj  # noqa: E402
from logger.utils.timestamp import DATE_FORMAT  # noqa: E402
from server.server_api import ServerAPI  # noqa: E402

from app.db.session import AsyncSessionLocal
from app.db import cruise as crud_cruise
from app.db import log_messages as crud_log_messages
from app.db import loggers as crud_loggers
from app.db import logger_configs as crud_logger_configs
from app.db import logger_config_state as crud_logger_config_state
from app.db import modes as crud_modes

################################################################################
class FastAPIServerAPI(ServerAPI):
    """API for interacting with OpenRVDAS data store."""

    def __init__(self):
        super().__init__()

    ############################################################################
    # ------------------- Internal session helpers ----------------------------#
    ############################################################################

    async def _with_session(self, func, *args, **kwargs):
        """Helper to manage a single session for a function."""
        async with AsyncSessionLocal() as session:
            return await func(session, *args, **kwargs)

    async def _with_transaction(self, func, *args, **kwargs):
        """Helper to manage a single session and wrap writes in a transaction."""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                return await func(session, *args, **kwargs)

    ############################################################################
    # ---------------------- Query Methods -----------------------------------#
    ############################################################################

    #############################
    async def get_configuration(self):
        async def _inner(session):
            cruise = await crud_cruise.get_cruise(session)
            active_mode_obj = await crud_modes.get_active_mode(session)
            default_mode_obj = await crud_modes.get_default_mode(session)

            active_mode = active_mode_obj.name if active_mode_obj else None
            default_mode = default_mode_obj.name if default_mode_obj else None

            modes_db = await crud_modes.list_modes(session)
            loggers = await crud_loggers.list_loggers(session)
            logger_map = {l.id: l.name for l in loggers}

            modes = {}
            for mode in modes_db:
                configs = await crud_modes.get_logger_configs_for_mode(session, mode.id)
                modes[mode.name] = {
                    logger_map[cfg.logger_id]: cfg.name
                    for cfg in configs
                    if cfg.logger_id in logger_map
                }

            return {
                "id": cruise.id if cruise else None,
                "start": cruise.start if cruise else None,
                "end": cruise.end if cruise else None,
                "config_filename": cruise.config_filename if cruise else None,
                "loaded_time": cruise.loaded_time if cruise else None,
                "active_mode": active_mode,
                "default_mode": default_mode,
                "modes": modes,
            }

        return await self._with_session(_inner)

    #############################
    async def get_modes(self):
        """Get the list of modes from the data store.
        > api.get_modes()
            ["off", "port", "underway"]
        """
        return await self._with_session(lambda session: 
            crud_modes.list_modes(session)
        )

    #############################
    async def get_active_mode(self):
        """Get the currently active mode from the data store.
        > api.get_active_mode()
            "port"
        """
        async def _inner(session):
            mode = await crud_modes.get_active_mode(session)
            return mode.name if mode else None
        return await self._with_session(_inner)

    #############################
    async def get_default_mode(self):
        """Get the default mode from the data store.
        > api.get_default_mode()
            "off"
        """
        async def _inner(session):
            mode = await crud_modes.get_default_mode(session)
            return mode.name if mode else None
        return await self._with_session(_inner)

    #############################
    async def get_loggers(self):
        """Get the dict of {logger_id:logger_spec,...} from the data store.
        > api.get_loggers()
            {
              "knud": {"host": "knud.pi", "configs":...},
              "gyr1": {"configs":...}
            }
        """
        async def _inner(session):
            loggers = await crud_loggers.list_loggers(session)
            return {
                logger.name: {"configs": [cfg.name for cfg in logger.configs]}
                for logger in loggers if logger.name
            }
        return await self._with_session(_inner)

    #############################
    async def get_logger(self, logger_id):
        """Retrieve the logger spec for the specified logger id.
        > api.get_logger('knud')
            {"name": "knud->net", "host_id": "knud.pi", "configs":...}
        """
        async def _inner(session):
            logger = await crud_loggers.get_logger_by_name(session, logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")
            return {"configs": [cfg.name for cfg in logger.configs]}
        return await self._with_session(_inner)

    #############################
    async def get_logger_config(self, config_name):
        """Retrieve the logger config associated with the specified name.
        > api.get_logger_config('knud->net')
               { "readers": [...], "transforms": [...], "writers": [...] }
        """
        async def _inner(session):
            cfg = await crud_logger_configs.get_logger_config_by_name(session, config_name)
            if not cfg:
                raise KeyError(f"Logger Config {config_name} not found")
            return cfg.config_json
        return await self._with_session(_inner)

    #############################
    async def get_logger_configs(self, mode=None):
        """Retrieve the configs associated with a mode from the data store.
        If mode is omitted, retrieve configs associated with the active mode.
        > api.get_logger_configs()
               {"knud": { config_spec },
                "gyr1": { config_spec }
               }
        """
        async def _inner(session):
            if mode is None:
                mode_obj = await crud_modes.get_active_mode(session)
                if not mode_obj:
                    raise KeyError("No active mode")
            else:
                mode_obj = await crud_modes.get_mode_by_name(session, mode)
                if not mode_obj:
                    raise KeyError(f"Mode {mode} not found")

            configs = await crud_modes.get_logger_configs_for_mode(session, mode_obj.id)
            loggers = await crud_loggers.list_loggers(session)
            logger_map = {logger.id: logger.name for logger in loggers}

            return {
                logger_map[cfg.logger_id]: cfg.config_json
                for cfg in configs
                if cfg.logger_id in logger_map
            }
        return await self._with_session(_inner)

    #############################
    async def get_logger_config_name(self, logger_id, mode=None):
        """Retrieve the name of the logger config associated with the
        specified logger in the specified mode. If mode is omitted,
        retrieve config name associated with the active mode.
        > api.get_logger_config_name('knud')
            knud->net
       """
        async def _inner(session):
            if mode is None:
                mode_obj = await crud_modes.get_active_mode(session)
                if not mode_obj:
                    raise KeyError("No active mode")
            else:
                mode_obj = await crud_modes.get_mode_by_name(session, mode)
                if not mode_obj:
                    raise KeyError(f"Mode {mode} not found")

            configs = await crud_modes.get_logger_configs_for_mode(session, mode_obj.id)
            logger = await crud_loggers.get_logger_by_name(session, logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")

            for cfg in configs:
                if cfg.logger_id == logger.id:
                    return cfg.name
            raise KeyError(f"No LoggerConfig for logger {logger_id} in mode {mode}")

        return await self._with_session(_inner)

    #############################
    async def get_logger_config_names(self, logger_id):
        """Retrieve list of logger config names for the specified logger.
        > api.get_logger_config_names('knud')
            ["off", "knud->net", "knud->net/file", "knud->net/file/db"]
        """
        async def _inner(session):
            logger = await crud_loggers.get_logger_by_name(session, logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")

            configs = await crud_logger_configs.get_logger_configs_for_logger(session, logger.id)
            return [cfg.name for cfg in configs] if configs else []
        return await self._with_session(_inner)

    ############################
    async def get_status(self, since_timestamp=None):
        """Retrieve a dict of the most-recent status report from each
        logger. If since_timestamp is specified, retrieve all status reports
        since that time."""

        async def _inner(session):
            if since_timestamp is None:
                return await crud_logger_config_state.get_latest_status_per_logger(session)
            return await crud_logger_config_state.get_status_since_per_logger(session, since_timestamp)

        states = await self._with_session(_inner)
        return = crud_logger_config_state.reformat_status_by_timestamp_with_names(
            [s for states_list in states.values() for s in states_list]
        )

    ############################
    async def get_message_log(self, source=None, user=None, log_level=sys.maxsize,
                        since_timestamp=None):
        """Retrieve log messages from source at or above log_level since
        timestamp. If source is omitted, retrieve from all sources. If
        log_level is omitted, retrieve at all levels. If since_timestamp is
        omitted, only retrieve most recent message.
        """
        async def _inner(session):
            log_messages = await crud_log_messages.get_log_messages(session, source=source, user=user, log_level=log_level, since_timestamp=since_timestamp)

            return [(message.timestamp.timestamp(), message.source,
                     message.user, message.log_level, message.message)
                    for message in log_messages]

        return await self._with_session(_inner)

    ############################################################################
    # ---------------------- Write Methods -----------------------------------#
    ############################################################################

    ############################
    async def message_log(self, source, user, log_level, message):
        """Timestamp and store the passed message."""
        async def _inner(session):
            await crud_log_messages.create_log_message(session, source=source, user=user, log_level=log_level, message=message)
        await self._with_transaction(_inner)


    async def update_status(self, status: Dict[str, Dict[str, Any]]) -> None:
        """
        Save/register the loggers' retrieved status report using CRUD functions.

        Parameters
        ----------
        status : Dict[str, Dict[str, Any]]
            Dictionary keyed by logger_id, each value a dict with:
                - config: str
                - errors: list[str]
                - pid: Optional[int]
                - failed: Optional[bool]
                - running: Optional[bool]
        """

        async def _inner(session):
            logging.debug("Writing updated status to database:\n%s", status)

            # Fetch the latest state per logger using CRUD
            latest_states: Dict[str, LoggerConfigState] = await get_latest_status_per_logger(session)

            for logger_id, logger_report in status.items():
                config_id = logger_report.get("config")
                logger_errors = logger_report.get("errors") or []
                logger_pid = logger_report.get("pid")
                logger_failed = logger_report.get("failed")
                logger_running = logger_report.get("running")

                # Normalize errors into string
                error_text = "\n".join(logger_errors) if logger_errors else None

                # Retrieve the most recent stored state for this logger (from CRUD dict)
                stored_state: LoggerConfigState | None = latest_states.get(logger_id)

                # Determine if a new row is needed
                if stored_state is None:
                    # No previous state → create new
                    await create_or_update_logger_config_state(
                        session,
                        config_id=config_id,
                        logger_id=logger_id,
                        running=logger_running,
                        failed=logger_failed,
                        pid=logger_pid,
                        errors=error_text,
                    )
                    continue

                # Compare fields to see if anything changed
                changed = (
                    bool(logger_errors)
                    or stored_state.running != logger_running
                    or stored_state.failed != logger_failed
                    or stored_state.pid != logger_pid
                )

                # Use the CRUD function to insert/update as necessary
                await create_or_update_logger_config_state(
                    session,
                    config_id=config_id,
                    logger_id=logger_id,
                    running=logger_running if changed else None,
                    failed=logger_failed if changed else None,
                    pid=logger_pid if changed else None,
                    errors=error_text if changed else None,
                )

        await self._with_transaction(_inner)            

    #############################
    async def set_active_mode(self, mode):
        """Set the active mode for OpenRVDAS.
        > api.set_active_mode(port')
        """
        async def _inner(session):
            mode_obj = await crud_modes.get_mode_by_name(session, mode)
            if not mode_obj:
                raise KeyError(f"Mode {mode} not found")
            await crud_modes.set_active_mode(session, mode_obj.id)

            configs = await crud_modes.get_logger_configs_for_mode(session, mode_obj.id)
            for cfg in configs:
                await crud_logger_config_state.create_or_update_logger_config_state(
                    session, config_id=cfg.id, logger_id=cfg.logger_id, running=False, pid=0
                )

        await self._with_transaction(_inner)
        self.signal_update()

    #############################
    async def set_active_logger_config(self, logger, config_name):
        """Set the active logger config for the specified logger to
        the specific logger_config name.
        > api.set_active_logger_config('knud', 'knud->file/net/db')
        """
        async def _inner(session):
            logger_obj = await crud_loggers.get_logger_by_name(session, logger)
            if not logger_obj:
                raise KeyError(f"Logger {logger} not found")
            config = await crud_logger_configs.get_logger_config_by_name(session, config_name)
            if not config:
                raise KeyError(f"Logger Config {config_name} not found")
            await crud_logger_config_state.create_or_update_logger_config_state(
                session, config_id=config.id, logger_id=logger_obj.id, running=False, pid=0
            )
        await self._with_transaction(_inner)
        self.signal_update()

    #############################
    async def add_cruise(self, cruise_id, start=None, end=None):
        """Add a new cruise_id to the data store. Use methods below to build
        it out.
        > api.add_cruise('NBP1702', '2017-02-02', '2017-03-01')
        """
        async def _inner(session):
            await crud_cruise.delete_cruise(session)
            cruise_start = datetime_obj(start, DATE_FORMAT) if isinstance(start, str) else start
            cruise_end = datetime_obj(end, DATE_FORMAT) if isinstance(end, str) else end
            await crud_cruise.create_or_update_cruise(
                session, cruise_id=cruise_id, start=cruise_start, end=cruise_end
            )
        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def delete_cruise(self):
        """Delete the cruise if it exists."""
        async def _inner(session):
            try:
                await crud_cruise.delete_cruise(session)
            except Exception:
                logging.exception("Failed to delete cruise")
                raise

        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def add_mode(self, mode):
        """Add a new mode to the OpenRVDAS configuration.
        > api.add_mode('underway')
        """
        async def _inner(session):
            await crud_modes.create_mode(session, name=mode, logger_config_ids=[])
        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def delete_mode(self, mode):
        """Delete the named mode (and all its configs) from the data store.
        If the deleted mode is the active mode, set the active mode to the default mode.
        > api.delete_mode('underway')
        """
        async def _inner(session):
            mode_obj = await crud_modes.get_mode_by_name(session, mode)
            if not mode_obj:
                raise KeyError(f"Mode {mode} not found")

            # If deleting the active mode, switch to default
            active_mode = await crud_modes.get_active_mode(session)
            if active_mode and active_mode.id == mode_obj.id:
                default_mode = await crud_modes.get_default_mode(session)
                if default_mode:
                    await crud_modes.set_active_mode(session, default_mode.id)

            await crud_modes.delete_mode(session, mode_obj.id)

        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def add_logger(self, logger_id, logger_config):
        """Add a new logger to the data store.

        logger_config - a dict defining:
          host - optional restriction on which host logger must run
          configs - list of logger_config names
        > api.add_logger(gyr2', { 'host_id': <host_id>, 'configs': [....] })
        """
        async def _inner(session):
            logger = await crud_loggers.create_logger(session, name=logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} could not be created")
            for config_name in logger_config.get("configs", []):
                cfg = await crud_logger_configs.get_logger_config_by_name(session, config_name)
                if not cfg:
                    raise KeyError(f"Logger Config {config_name} not found")
                await crud_loggers.upsert_logger_config_for_logger(session, logger.id, cfg.id)
        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def delete_logger(self, logger_id):
        """Remove a logger and all its associated logger_configs from the data store.
        > api.delete_logger('gyr2')
        """
        async def _inner(session):
            logger = await crud_loggers.get_logger_by_name(session, logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")

            await crud_loggers.delete_logger(session, logger.id)

        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def add_logger_config(self, logger_config_name, logger_config_spec):
        """Add a new logger config to the data store.
        > api.add_logger_config('gyr2->net/file/db', { logger_config_spec })
        """
        async def _inner(session):
            logger_name = logger_config_spec.get("logger_id")
            logger = await crud_loggers.get_logger_by_name(session, logger_name)
            if not logger:
                raise KeyError(f"Logger {logger_name} not found")
            await crud_logger_configs.create_logger_config(
                session,
                name=logger_config_name,
                config_json=logger_config_spec.get("config_json"),
                logger_id=logger.id,
                enabled=logger_config_spec.get("enabled", True),
            )
        await self._with_transaction(_inner)
        self.signal_load()

    #############################
    async def add_logger_config_to_logger(self, config, logger_id):
        """Associate a config with a logger.
        > api.add_logger_config_to_logger('gyr2->net/file/db', 'gyr2')
        """
        async def _inner(session):
            logger = await crud_loggers.get_logger_by_name(session, logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")
            cfg = await crud_logger_configs.get_logger_config_by_name(session, config)
            if not cfg:
                raise KeyError(f"Logger config {config} not found")
            await crud_loggers.upsert_logger_config_for_logger(session, logger.id, cfg.id)
        await self._with_transaction(_inner)
        self.signal_update()

    #############################
    async def add_logger_config_to_mode(self, config, logger_id, mode):
        """Associate a config with a logger and mode.
        > api.add_logger_config_to_mode('gyr2->net/file/db', 'gyr2', 'underway')
        """
        async def _inner(session):
            logger = await crud_loggers.get_logger_by_name(session, logger_id)
            if not logger:
                raise KeyError(f"Logger {logger_id} not found")
            cfg = await crud_logger_configs.get_logger_config_by_name(session, config)
            if not cfg:
                raise KeyError(f"Logger config {config} not found")
            mode_obj = await crud_modes.get_mode_by_name(session, mode)
            if not mode_obj:
                raise KeyError(f"Mode {mode} not found")
            await crud_modes.upsert_logger_config_for_mode(session, mode_obj.id, logger.id, cfg.id)
        await self._with_transaction(_inner)
        self.signal_update()

    #############################
    async def delete_logger_config(self, config_id):
        """Delete specified config from data store (and by extension,
        from the mode and logger with which it is associated.
        > api.delete_logger_config('gyr2->net/file/db')
        """
        async def _inner(session):
            cfg = await crud_logger_configs.get_logger_config_by_name(session, config_id)
            if not cfg:
                raise KeyError(f"Logger config {config_id} not found")
            await crud_logger_configs.delete_logger_config(session, cfg.id)
        await self._with_transaction(_inner)
        self.signal_load()


    #############################
    async def load_configuration(self, configuration):
        """
        Load a complete cruise configuration into the data store.
        > api.load_configuration({ configuration })
        """
        cruise_conf = configuration.get('cruise', {})
        loggers_conf = configuration.get('loggers')
        modes_conf = configuration.get('modes')
        default_mode_name = configuration.get('default_mode')
        configs_conf = configuration.get('configs')
        preserve_mode = configuration.get('preserve_mode', False)

        # Sanity checks
        if loggers_conf is None:
            raise ValueError("Cruise definition has no loggers")
        if modes_conf is None:
            raise ValueError("Cruise definition has no modes")
        if configs_conf is None:
            raise ValueError("Cruise definition has no configs")

        # Ensure configs have names
        for cfg_name, cfg in configs_conf.items():
            if cfg is None:
                raise ValueError(f'No logger for "{cfg_name}" in cruise definition')
            cfg.setdefault("name", cfg_name)

        # Validate modes reference existing loggers/configs
        for mode_name, mode_loggers in modes_conf.items():
            for logger_name, cfg_name in mode_loggers.items():
                if logger_name not in loggers_conf:
                    raise ValueError(f'Mode "{mode_name}" references undefined logger "{logger_name}"')
                if cfg_name not in configs_conf:
                    raise ValueError(f'Mode "{mode_name}" references undefined config "{cfg_name}" for logger "{logger_name}"')

        if default_mode_name and default_mode_name not in modes_conf:
            raise ValueError(f'Default mode "{default_mode_name}" is not in valid modes: {list(modes_conf.keys())}')

        cruise_id = cruise_conf.get('id', 'Cruise')
        cruise_start = datetime_obj(cruise_conf.get('start'), DATE_FORMAT) if cruise_conf.get('start') else None
        cruise_end = datetime_obj(cruise_conf.get('end'), DATE_FORMAT) if cruise_conf.get('end') else None
        config_filename = cruise_conf.get('config_filename')

        async def _inner(session):
            # --- Cruise ---
            await crud_cruise.delete_cruise(session)
            await crud_cruise.create_or_update_cruise(
                session, cruise_id=cruise_id, start=cruise_start, end=cruise_end, config_filename=config_filename
            )

            # Preserve active/default modes if requested
            prev_active_mode = await crud_modes.get_active_mode(session) if preserve_mode else None
            prev_default_mode = await crud_modes.get_default_mode(session) if preserve_mode else None

            # --- Modes ---
            # Delete old modes
            for mode in await crud_modes.list_modes(session):
                await crud_modes.delete_mode(session, mode.id)

            # Create new modes
            mode_objs = {}
            for mode_name in modes_conf:
                is_active = preserve_mode and prev_active_mode and mode_name == prev_active_mode.name
                is_default = (preserve_mode and prev_default_mode and mode_name == prev_default_mode.name) \
                             or (not preserve_mode and mode_name == default_mode_name)
                mode_objs[mode_name] = await crud_modes.create_mode(
                    session, name=mode_name, logger_config_ids=[], is_active=is_active, is_default=is_default
                )

            # --- Loggers ---
            logger_objs = {}
            for logger_name in loggers_conf:
                logger = await crud_loggers.get_logger_by_name(session, logger_name)
                if logger is None:
                    logger = await crud_loggers.create_logger(session, name=logger_name)
                logger_objs[logger_name] = logger

            # --- Logger Configs ---
            config_objs = {}
            for cfg_name, cfg_spec in configs_conf.items():
                # Find which logger this config belongs to
                logger_name = next((ln for ln, spec in loggers_conf.items() if cfg_name in spec.get('configs', [])), None)
                if not logger_name:
                    raise ValueError(f'Config "{cfg_name}" not associated with any logger')
                logger = logger_objs[logger_name]

                # Create or update
                cfg = await crud_logger_configs.get_logger_config_by_name(session, cfg_name)
                if cfg:
                    cfg = await crud_logger_configs.update_logger_config(
                        session, config_id=cfg.id, logger_id=logger.id, config_json=cfg_spec
                    )
                else:
                    cfg = await crud_logger_configs.create_logger_config(
                        session, name=cfg_name, logger_id=logger.id, config_json=cfg_spec
                    )
                config_objs[cfg_name] = cfg

            # --- Associate logger configs with modes ---
            for mode_name, mode_dict in modes_conf.items():
                mode = mode_objs[mode_name]
                for logger_name, cfg_name in mode_dict.items():
                    logger = logger_objs[logger_name]
                    cfg = config_objs[cfg_name]
                    await crud_modes.upsert_logger_config_for_mode(
                        session, mode_id=mode.id, logger_id=logger.id, config_id=cfg.id
                    )

        # Execute entire load in a single transaction/session
        await self._with_transaction(_inner)

    #############################
    async def delete_configuration(self):
        """Remove the entire cruise configuration from the data store.
        > api.delete_configuration()
        """
        async def _inner(session):
            try:
                # Delete the cruise
                await crud_cruise.delete_cruise(session)

                # Delete all modes
                for mode in await crud_modes.list_modes(session):
                    await crud_modes.delete_mode(session, mode.id)

                # Delete all loggers
                for logger in await crud_loggers.list_loggers(session):
                    await crud_loggers.delete_logger(session, logger.id)

                # Delete all logger configs
                for cfg in await crud_logger_configs.list_logger_configs(session):
                    await crud_logger_configs.delete_logger_config(session, cfg.id)

            except Exception:
                logging.exception("Failed to delete configuration")
                raise

        # Execute all deletions in a single session/transaction
        await self._with_transaction(_inner)

        # Notify observers that configuration has been deleted
        self.signal_load()

