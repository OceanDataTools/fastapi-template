# app/schemas.py
from datetime import datetime
from typing import Optional, List

from pydantic import UUID4, BaseModel, Extra, Field


# -------------------
# Cruise
# -------------------
class CruiseBase(BaseModel):
    start: Optional[datetime] = Field(None, description="Start datetime of the Cruise")
    end: Optional[datetime] = Field(None, description="End datetime of the Cruise")
    config_filename: Optional[str] = Field(None, description="Optional config filename")
    config_text: Optional[str] = Field(None, description="Optional config text")


class CruiseCreate(CruiseBase):
    cruise_id: str = Field(..., description="Identifier for the Cruise")

class CruiseUpdate(CruiseBase):
    pass  # All fields optional for PATCH

class CruiseRead(CruiseBase):
    cruise_id: str

    model_config = {"from_attributes": True, "extra": Extra.ignore}


# -------------------
# Logger
# -------------------
class LoggerBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None


class LoggerCreate(LoggerBase):
    pass


class LoggerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class LoggerOut(LoggerBase):
    id: UUID4

    model_config = {"from_attributes": True, "extra": Extra.ignore}


# -------------------
# Logger Config
# -------------------
class LoggerConfigBase(BaseModel):
    name: str
    description: Optional[str] = None
    logger_id: Optional[UUID4] = None


class LoggerConfigCreate(LoggerConfigBase):
    pass


class LoggerConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    logger_id: Optional[UUID4] = None


class LoggerConfigOut(LoggerConfigBase):
    id: UUID4

    model_config = {"from_attributes": True, "extra": Extra.ignore}


# -------------------
# Mode
# -------------------
class ModeBase(BaseModel):
    name: str = Field(..., max_length=255)


class ModeCreate(ModeBase):
    logger_config_ids: List[UUID4] = []
    is_default: bool | None = None

class ModeUpdate(BaseModel):
    name: str | None = None
    logger_config_ids: List[UUID4] | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class ModeOut(ModeBase):
    id: UUID4
    is_active: bool
    is_default: bool
    logger_config_ids: List[UUID4]

    model_config = {"from_attributes": True, "extra": Extra.ignore}


# -------------------
# Loggers
# -------------------
class LoggerBase(BaseModel):
    name: Optional[str] = Field(None, max_length=255)


class LoggerCreate(LoggerBase):
    pass


class LoggerUpdate(LoggerBase):
    pass


class LoggerConfigRef(BaseModel):
    id: str
    name: Optional[str]

    model_config = {"from_attributes": True, "extra": Extra.ignore}


class LoggerOut(LoggerBase):
    id: str
    configs: List[LoggerConfigRef] = []

    model_config = {"from_attributes": True, "extra": Extra.ignore}


# -------------------
# Logger Configs
# -------------------
class LoggerConfigBase(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    config_json: Optional[str]
    enabled: Optional[bool] = True
    logger_id: Optional[str]


class LoggerConfigCreate(LoggerConfigBase):
    config_json: str


class LoggerConfigUpdate(LoggerConfigBase):
    pass


class LoggerRef(BaseModel):
    id: str
    name: Optional[str]

    model_config = {"from_attributes": True, "extra": Extra.ignore}


class LoggerConfigOut(LoggerConfigBase):
    id: str
    logger: Optional[LoggerRef]

    model_config = {"from_attributes": True, "extra": Extra.ignore}