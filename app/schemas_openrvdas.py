# app/schemas.py
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field, field_serializer


# -------------------
# Cruise
# -------------------
class CruiseBase(BaseModel):
    start: Optional[datetime] = Field(None, description="Start datetime of the Cruise")
    end: Optional[datetime] = Field(None, description="End datetime of the Cruise")
    config_filename: Optional[str] = Field(None, description="Optional config filename")


class CruiseCreate(CruiseBase):
    cruise_id: str = Field(..., description="Identifier for the Cruise")


class CruiseUpdate(CruiseBase):
    pass  # All fields optional for PATCH


class CruiseRead(CruiseBase):
    cruise_id: str
    config_file_changed: bool = False

    model_config = {"from_attributes": True, "extra": "ignore"}


# -------------------
# Refs
# -------------------
class ConfigRef(BaseModel):
    id: str

    model_config = {"from_attributes": True, "extra": "ignore"}


class LoggerRef(BaseModel):
    id: str

    model_config = {"from_attributes": True, "extra": "ignore"}


# -------------------
# Mode
# -------------------
class ModeBase(BaseModel):
    id: str = Field(..., max_length=255)


class ModeCreate(ModeBase):
    config_ids: List[str] = []
    default: bool | None = None


class ModeUpdate(BaseModel):
    config_ids: List[str] | None = None
    active: bool | None = None
    default: bool | None = None


class ModeOut(ModeBase):
    id: str
    active: bool
    default: bool
    configs: List[ConfigRef] = Field(default_factory=list)

    model_config = {"from_attributes": True, "extra": "ignore"}

    @field_serializer("configs")
    def serialize_configs(self, v, info):
        return [c.id for c in v]


# -------------------
# Loggers
# -------------------
class LoggerBase(BaseModel):
    id: str = Field(None, max_length=255)


class LoggerCreate(LoggerBase):
    pass


class LoggerUpdate(LoggerBase):
    pass


class LoggerOut(BaseModel):
    id: str
    configs: List[ConfigRef] = Field(default_factory=list)
    active_config: Optional[str] = None
    running: bool = False

    model_config = {"from_attributes": True, "extra": "ignore"}

    # ORM Config -> string IDs
    @field_serializer("configs")
    def serialize_configs(self, v, info):
        return [c.id for c in v]

    @field_serializer("active_config")
    def serialize_active_config(self, v, info):
        return v


# -------------------
# Configs
# -------------------
class ConfigBase(BaseModel):
    id: Optional[str] = Field(None, max_length=255)
    config_json: Optional[str]
    logger_id: Optional[str]


class ConfigCreate(ConfigBase):
    config_json: str


class ConfigUpdate(ConfigBase):
    pass


class ConfigOut(ConfigBase):

    model_config = {"from_attributes": True, "extra": "ignore"}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active(self) -> bool:
        for state in getattr(self, "states", []):
            if state.running:
                return True
        return False
