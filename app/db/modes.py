from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import selectinload

from app.models_openrvdas import Mode, LoggerConfig


async def list_modes(session: AsyncSession) -> List[Mode]:
    result = await session.execute(
        select(Mode)
        .options(selectinload(Mode.logger_configs))
        .order_by(Mode.name)
    )
    return result.scalars().all()


async def get_mode(session: AsyncSession, mode_id: str) -> Optional[Mode]:
    result = await session.execute(
        select(Mode)
        .options(selectinload(Mode.logger_configs))
        .where(Mode.id == mode_id)
    )
    return result.scalar_one_or_none()


async def get_mode_by_name(session: AsyncSession, name: str) -> Optional[Mode]:
    result = await session.execute(
        select(Mode).where(Mode.name == name)
    )
    return result.scalar_one_or_none()


async def get_active_mode(session: AsyncSession) -> Optional[Mode]:
    result = await session.execute(select(Mode).where(Mode.is_active.is_(True)))
    return result.scalar_one_or_none()


async def get_default_mode(session: AsyncSession) -> Optional[Mode]:
    result = await session.execute(select(Mode).where(Mode.is_default.is_(True)))
    return result.scalar_one_or_none()


async def validate_mode_configs(session: AsyncSession, config_ids: List):
    if not config_ids:
        return

    result = await session.execute(
        select(LoggerConfig).where(LoggerConfig.id.in_(config_ids))
    )
    configs = result.scalars().all()

    logger_map = {}
    for cfg in configs:
        if cfg.logger_id:
            if cfg.logger_id in logger_map:
                raise ValueError(
                    "Mode cannot include multiple LoggerConfigs for the same Logger"
                )
            logger_map[cfg.logger_id] = cfg.id


async def create_mode(
    session: AsyncSession,
    name: str,
    logger_config_ids: List,
    is_active: Optional[bool] = False,
    is_default: Optional[bool] = False,
) -> Mode:
    await validate_mode_configs(session, logger_config_ids)

    result = await session.execute(
        select(LoggerConfig).where(LoggerConfig.id.in_(logger_config_ids))
    )
    configs = result.scalars().all()

    mode = Mode(name=name, logger_configs=configs, is_active=is_active, is_default=is_default)
    session.add(mode)
    await session.commit()
    await session.refresh(mode)
    return mode


async def update_mode(
    session: AsyncSession,
    mode_id,
    *,
    name: Optional[str] = None,
    logger_config_ids: Optional[List] = None,
    is_active: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Mode:
    result = await session.execute(select(Mode).where(Mode.id == mode_id))
    mode = result.scalar_one_or_none()

    if not mode:
        raise NoResultFound("Mode not found")

    # Update name
    if name is not None:
        mode.name = name

    # Update logger configs
    if logger_config_ids is not None:
        # Validate constraint: one config per logger
        result = await session.execute(
            select(LoggerConfig).where(LoggerConfig.id.in_(logger_config_ids))
        )
        configs = result.scalars().all()

        logger_ids = set()
        for cfg in configs:
            if cfg.logger_id:
                if cfg.logger_id in logger_ids:
                    raise ValueError(
                        "Mode cannot include multiple LoggerConfigs for the same Logger"
                    )
                logger_ids.add(cfg.logger_id)

        mode.logger_configs = configs

    # Handle activation
    if is_active is True:
        await session.execute(update(Mode).values(is_active=False))
        mode.is_active = True
    elif is_active is False:
        mode.is_active = False

    # Handle setting default
    if is_default is True:
        await session.execute(update(Mode).values(is_default=False))
        mode.is_default = True
    elif is_default is False:
        mode.is_default = False


    await session.commit()
    await session.refresh(mode)

    return mode

async def delete_mode(session: AsyncSession, mode_id: str) -> None:
    result = await session.execute(
        select(Mode).where(Mode.id == mode_id)
    )
    mode = result.scalar_one_or_none()

    if not mode:
        raise NoResultFound(f"Mode with id {mode_id} not found")

    if mode.is_active:
        raise ValueError("Cannot delete the active mode")

    if mode.is_default:
        raise ValueError("Cannot delete the default mode")

    await session.delete(mode)
    await session.commit()


async def set_active_mode(session: AsyncSession, mode_id):
    # deactivate all
    await session.execute(update(Mode).values(is_active=False))

    result = await session.execute(select(Mode).where(Mode.id == mode_id))
    mode = result.scalar_one_or_none()

    if not mode:
        raise NoResultFound("Mode not found")

    mode.is_active = True
    await session.commit()
    await session.refresh(mode)
    return mode


async def set_default_mode(session: AsyncSession, mode_id):
    # deactivate all
    await session.execute(update(Mode).values(is_default=False))

    result = await session.execute(select(Mode).where(Mode.id == mode_id))
    mode = result.scalar_one_or_none()

    if not mode:
        raise NoResultFound("Mode not found")

    mode.is_default = True
    await session.commit()
    await session.refresh(mode)
    return mode


async def assign_logger_configs_to_mode(
    session: AsyncSession,
    mode_id: str,
    logger_config_ids: list[str],
) -> Mode:
    """
    Assign a list of LoggerConfig IDs to a Mode.
    Ensures no two LoggerConfigs for the same Logger are in the mode.
    """
    result = await session.execute(select(Mode).where(Mode.id == mode_id))
    mode = result.scalar_one_or_none()
    if not mode:
        raise NoResultFound("Mode not found")

    # Fetch LoggerConfigs
    result = await session.execute(
        select(LoggerConfig).where(LoggerConfig.id.in_(logger_config_ids))
    )
    configs = result.scalars().all()

    # Validate uniqueness per logger
    seen_logger_ids = set()
    for cfg in configs:
        if cfg.logger_id:
            if cfg.logger_id in seen_logger_ids:
                raise ValueError(
                    "Cannot assign multiple LoggerConfigs for the same Logger to a Mode"
                )
            seen_logger_ids.add(cfg.logger_id)

    mode.logger_configs = configs
    await session.commit()
    await session.refresh(mode)
    return mode


async def upsert_logger_config_for_mode(
    session: AsyncSession,
    mode_id: str,
    logger_id: str,
    config_id: str,
) -> Mode:
    result = await session.execute(
        select(Mode)
        .options(selectinload(Mode.logger_configs))
        .where(Mode.id == mode_id)
    )
    mode = result.scalar_one_or_none()
    if not mode:
        raise NoResultFound("Mode not found")

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
    mode.logger_configs = [
        cfg for cfg in mode.logger_configs
        if cfg.logger_id != logger_id
    ]

    # Add new config
    mode.logger_configs.append(new_cfg)

    await session.commit()
    await session.refresh(mode)
    return mode


async def remove_logger_config_from_mode(
    session: AsyncSession,
    mode_id: str,
    config_id: str,
) -> Mode:
    """
    Remove a single LoggerConfig from a Mode.
    """
    result = await session.execute(select(Mode).where(Mode.id == mode_id))
    mode = result.scalar_one_or_none()
    if not mode:
        raise NoResultFound("Mode not found")

    mode.logger_configs = [cfg for cfg in mode.logger_configs if cfg.id != config_id]

    await session.commit()
    await session.refresh(mode)
    return mode