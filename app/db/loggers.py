from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.models_openrvdas import Logger


async def list_loggers(session: AsyncSession) -> List[Logger]:
    result = await session.execute(select(Logger))
    return result.scalars().all()


async def get_logger(session: AsyncSession, logger_id) -> Optional[Logger]:
    result = await session.execute(select(Logger).where(Logger.id == logger_id))
    return result.scalar_one_or_none()


async def create_logger(session: AsyncSession, **data) -> Logger:
    logger = Logger(**data)
    session.add(logger)
    await session.commit()
    await session.refresh(logger)
    return logger


async def update_logger(session: AsyncSession, logger_id, **data) -> Logger:
    logger = await get_logger(session, logger_id)
    if not logger:
        raise NoResultFound("Logger not found")

    for key, value in data.items():
        if value is not None:
            setattr(logger, key, value)

    await session.commit()
    await session.refresh(logger)
    return logger


async def delete_logger(session: AsyncSession, logger_id):
    logger = await get_logger(session, logger_id)
    if not logger:
        raise NoResultFound("Logger not found")

    await session.delete(logger)
    await session.commit()


async def get_logger_by_name(session: AsyncSession, name: str) -> Optional[Logger]:
    result = await session.execute(
        select(Logger).where(Logger.name == name)
    )
    return result.scalar_one_or_none()


async def upsert_logger_config_for_logger(
    session: AsyncSession,
    logger_id: str,
    config_id: str,
) -> Logger:
    result = await session.execute(
        select(Logger)
        .options(selectinload(Logger.logger_configs))
        .where(Logger.id == logger_id)
    )
    logger = result.scalar_one_or_none()
    if not logger:
        raise NoResultFound("Logger not found")

    # Fetch the new config
    result = await session.execute(
        select(LoggerConfig).where(LoggerConfig.id == config_id)
    )
    new_cfg = result.scalar_one_or_none()
    if not new_cfg:
        raise NoResultFound("LoggerConfig not found")

    if new_cfg.logger_id != logger_id:
        raise ValueError("LoggerConfig does not belong to specified logger")

    # Remove existing config for this logger
    logger.logger_configs = [
        cfg for cfg in logger.logger_configs
        if cfg.logger_id != logger_id
    ]

    # Add new config
    logger.logger_configs.append(new_cfg)

    await session.commit()
    await session.refresh(logger)
    return logger