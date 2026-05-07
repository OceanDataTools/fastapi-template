from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text, func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models import Base
from sqlalchemy import text

# -------------------
# Association table: Config <-> Mode
# -------------------
logger_config_modes = Table(
    "logger_config_modes",
    Base.metadata,
    Column("config_id", String(255), ForeignKey("configs.id", ondelete="CASCADE"), primary_key=True),
    Column("mode_id", String(255), ForeignKey("modes.id", ondelete="CASCADE"), primary_key=True),
)

# -------------------
# Cruise (metadata only)
# -------------------
class Cruise(Base):
    __tablename__ = "cruise"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    config_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    config_mtime_baseline: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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

    id: Mapped[str] = mapped_column(String(255), primary_key=True)

    configs: Mapped[List[Config]] = relationship("Config", back_populates="logger")
    config_states: Mapped[List[LoggerConfigState]] = relationship(
        "LoggerConfigState", back_populates="logger", passive_deletes="all"
    )

    def __repr__(self):
        return f"<Logger id={self.id}>"

# -------------------
# Config
# -------------------
class Config(Base):
    __tablename__ = "configs"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)

    logger_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("loggers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    logger: Mapped[Optional[Logger]] = relationship("Logger", back_populates="configs")

    modes: Mapped[List[Mode]] = relationship(
        "Mode", secondary=logger_config_modes, back_populates="configs"
    )

    states: Mapped[List[LoggerConfigState]] = relationship(
        "LoggerConfigState", back_populates="config", passive_deletes="all"
    )

    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self):
        return f"<Config id={self.id} config_json={self.config_json} active={self.active}>"

# -------------------
# LoggerConfigState
# -------------------
class LoggerConfigState(Base):
    __tablename__ = "logger_config_states"
    __table_args__ = (
        Index(
            "uq_logger_config_state_logger",
            "logger_id",
            "config_id",
            unique=True,
            postgresql_where=text("logger_id IS NOT NULL"),
        ),
        Index(
            "uq_logger_config_state_config_only",
            "config_id",
            unique=True,
            postgresql_where=text("logger_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    logger_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("loggers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    config_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("configs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    logger: Mapped[Optional[Logger]] = relationship("Logger", back_populates="config_states")
    config: Mapped[Config] = relationship("Config", back_populates="states")

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self):
        return f"<LoggerConfigState logger={self.logger_id} config={self.config_id}>"

# -------------------
# Mode
# -------------------
class Mode(Base):
    __tablename__ = "modes"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    configs: Mapped[List[Config]] = relationship(
        "Config", secondary=logger_config_modes, back_populates="modes"
    )

    def __repr__(self):
        return f"<Mode id={self.id} active={self.active} default={self.default}>"

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
