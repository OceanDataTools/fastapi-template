from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from typing import List, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, func, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# -------------------
# Declarative base
# -------------------
class Base(DeclarativeBase):
    pass

# -------------------
# Association table: LoggerConfig <-> Mode
# -------------------
logger_config_modes = Table(
    "logger_config_modes",
    Base.metadata,
    Column("logger_config_id", String(36), ForeignKey("logger_configs.id", ondelete="CASCADE")),
    Column("mode_id", String(36), ForeignKey("modes.id", ondelete="CASCADE")),
)

# -------------------
# Cruise (metadata only)
# -------------------
class Cruise(Base):
    __tablename__ = "cruises"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    config_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    config_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    loaded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<Cruise id={self.id}>"

# -------------------
# Logger
# -------------------
class Logger(Base):
    __tablename__ = "loggers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    # Reverse link to all LoggerConfigs for this logger
    configs: Mapped[List[LoggerConfig]] = relationship("LoggerConfig", back_populates="logger")

    # Reverse link to LoggerConfigState
    config_states: Mapped[List[LoggerConfigState]] = relationship(
        "LoggerConfigState", back_populates="logger", passive_deletes=True
    )

    def __repr__(self):
        return f"<Logger(id={self.id}, name={self.name})>"

# -------------------
# LoggerConfig
# -------------------
class LoggerConfig(Base):
    __tablename__ = "logger_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    # Optional association to a single Logger
    logger_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("loggers.id", ondelete="SET NULL"), nullable=True, index=True)
    logger: Mapped[Optional[Logger]] = relationship("Logger", back_populates="configs")

    # Many-to-many with Mode
    modes: Mapped[List[Mode]] = relationship("Mode", secondary=logger_config_modes, back_populates="logger_configs")

    # Reverse relationship to LoggerConfigState
    states: Mapped[List[LoggerConfigState]] = relationship("LoggerConfigState", back_populates="config", passive_deletes=True)

    # Configuration metadata
    current_config: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self):
        mode_names = [m.name for m in self.modes]
        return f"<LoggerConfig name={self.name} modes={mode_names}>"

# -------------------
# LoggerConfigState
# -------------------
class LoggerConfigState(Base):
    __tablename__ = "logger_config_states"
    __table_args__ = (
        # One state per (logger, config) when logger exists
        Index(
            "uq_logger_config_state_logger",
            "logger_id",
            "config_id",
            unique=True,
            postgresql_where=(Column("logger_id").isnot(None)),
        ),

        # One state per config when logger is NULL
        Index(
            "uq_logger_config_state_config_only",
            "config_id",
            unique=True,
            postgresql_where=(Column("logger_id").is_(None)),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    logger_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("loggers.id", ondelete="CASCADE"), nullable=True, index=True)
    config_id: Mapped[str] = mapped_column(String(36), ForeignKey("logger_configs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Relationships
    logger: Mapped[Optional[Logger]] = relationship("Logger", back_populates="config_states")
    config: Mapped[LoggerConfig] = relationship("LoggerConfig", back_populates="states")

    # Status fields
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self):
        return f"<LoggerConfigState logger={self.logger_id} config={self.config_id} running={self.running} failed={self.failed}>"

# -------------------
# Mode
# -------------------
class Mode(Base):
    __tablename__ = "modes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Many-to-many reverse relationship
    logger_configs: Mapped[List[LoggerConfig]] = relationship(
        "LoggerConfig", secondary=logger_config_modes, back_populates="modes"
    )

    def __repr__(self):
        return f"<Mode id={self.id} name={self.name} active={self.active} default={self.default}>"

# -------------------
# LastUpdate
# -------------------
class LastUpdate(Base):
    __tablename__ = "last_update"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<LastUpdate timestamp={self.timestamp}>"

# -------------------
# LogMessage
# -------------------
class LogMessage(Base):
    __tablename__ = "log_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    user: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    log_level: Mapped[Optional[int]] = mapped_column(Integer, default=0, nullable=True, index=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<LogMessage level={self.log_level} source={self.source} time={self.timestamp}>"
