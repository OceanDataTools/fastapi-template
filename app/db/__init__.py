from app.db.modes import ModeCRUD
from app.db.log_messages import LogMessageCRUD
from app.db.configs import ConfigCRUD
from app.db.loggers import LoggerCRUD
from app.db.cruise import CruiseCRUD
from app.db.logger_config_state import LoggerConfigStateCRUD

log_message_crud = LogMessageCRUD()
config_crud = ConfigCRUD()
logger_crud = LoggerCRUD(config_crud)
logger_config_state_crud = LoggerConfigStateCRUD(config_crud)
mode_crud = ModeCRUD(config_crud, logger_crud)
cruise_crud = CruiseCRUD()


