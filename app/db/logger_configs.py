from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.models_openrvdas import LoggerConfig


async def list_logger_configs(session: AsyncSession) -> List[LoggerConfig]:
    result = await session.execute(select(LoggerConfig))
    return result.scalars().all()


async def get_logger_config(session: AsyncSession, config_id) -> Optional[LoggerConfig]:
    result = await session.execute(
        select(LoggerConfig).where(LoggerConfig.id == config_id)
    )
    return result.scalar_one_or_none()


async def get_logger_configs_by_name(session: AsyncSession, name: str) -> Optional[LoggerConfig]:
    result = await session.execute(
        select(LoggerConfig).where(LoggerConfig.name == name)
    )
    return result.scalar_one_or_none()


async def get_logger_configs_for_mode(
    session: AsyncSession,
    mode_id: str,
) -> list[LoggerConfig]:
    result = await session.execute(
        select(Mode)
        .options(selectinload(Mode.logger_configs))
        .where(Mode.id == mode_id)
    )
    mode = result.scalar_one_or_none()
    if not mode:
        raise NoResultFound("Mode not found")

    return mode.logger_configs


async def get_logger_configs_for_logger(
    session: AsyncSession,
    logger_id: str,
) -> list[LoggerConfig]:
    result = await session.execute(
        select(Logger)
        .options(selectinload(Logger.logger_configs))
        .where(Logger.id == logger_id)
    )
    logger = result.scalar_one_or_none()
    if not logger:
        raise NoResultFound("Logger not found")

    return logger.logger_configs


async def create_logger_config(session: AsyncSession, **data) -> LoggerConfig:
    config = LoggerConfig(**data)
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def update_logger_config(session: AsyncSession, config_id, **data) -> LoggerConfig:
    config = await get_logger_config(session, config_id)
    if not config:
        raise NoResultFound("LoggerConfig not found")

    for key, value in data.items():
        if value is not None:
            setattr(config, key, value)

    await session.commit()
    await session.refresh(config)
    return config


async def delete_logger_config(session: AsyncSession, config_id):
    config = await get_logger_config(session, config_id)
    if not config:
        raise NoResultFound("LoggerConfig not found")

    await session.delete(config)
    await session.commit()
