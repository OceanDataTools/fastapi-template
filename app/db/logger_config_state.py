from typing import List, Optional
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.models_openrvdas import LoggerConfigState


# async def list_logger_config_states(
#     session: AsyncSession,
# ) -> List[LoggerConfigState]:
#     result = await session.execute(
#         select(LoggerConfigState)
#     )
#     return result.scalars().all()


# async def get_logger_config_state(
#     session: AsyncSession,
#     state_id: int,
# ) -> Optional[LoggerConfigState]:
#     result = await session.execute(
#         select(LoggerConfigState)
#         .where(LoggerConfigState.id == state_id)
#     )
#     return result.scalar_one_or_none()

async def get_logger_config_state_for_logger(
    session: AsyncSession,
    logger_id: str,
    since_timestamp: Optional[datetime] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[LoggerConfigState]:
    stmt = (
        select(LoggerConfigState)
        .where(LoggerConfigState.logger_id == logger_id)
        .order_by(desc(LoggerConfigState.timestamp))
    )

    if since_timestamp is not None:
        stmt = stmt.where(LoggerConfigState.timestamp >= since_timestamp)

    if limit is not None:
        stmt = stmt.limit(limit)

    if offset is not None:
        stmt = stmt.offset(offset)

    result = await session.execute(stmt)
    return result.scalars().all()


async def get_logger_config_state_for_config(
    session: AsyncSession,
    config_id: str,
    since_timestamp: Optional[datetime] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[LoggerConfigState]:
    stmt = (
        select(LoggerConfigState)
        .where(LoggerConfigState.config_id == config_id)
        .order_by(desc(LoggerConfigState.timestamp))
    )

    if since_timestamp is not None:
        stmt = stmt.where(LoggerConfigState.timestamp >= since_timestamp)

    if limit is not None:
        stmt = stmt.limit(limit)

    if offset is not None:
        stmt = stmt.offset(offset)

    result = await session.execute(stmt)
    return result.scalars().all()


async def get_latest_status_per_logger(
    session: AsyncSession,
) -> Dict[str, LoggerConfigState]:
    """
    Return the most recent LoggerConfigState for each logger,
    with Logger and LoggerConfig relationships loaded.
    """

    # Subquery to find latest timestamp per logger_id
    subq = (
        select(
            LoggerConfigState.logger_id,
            func.max(LoggerConfigState.timestamp).label("max_ts"),
        )
        .group_by(LoggerConfigState.logger_id)
        .subquery()
    )

    # Main query joining with subquery and eager-loading relationships
    stmt = (
        select(LoggerConfigState)
        .options(
            joinedload(LoggerConfigState.logger),
            joinedload(LoggerConfigState.config),
        )
        .join(
            subq,
            (LoggerConfigState.logger_id == subq.c.logger_id)
            & (LoggerConfigState.timestamp == subq.c.max_ts),
        )
    )

    result = await session.execute(stmt)
    states = result.scalars().all()

    # Use logger name if available, else fallback to logger_id
    return {state.logger.name if state.logger else state.logger_id: state for state in states}


async def get_status_since_per_logger(
    session: AsyncSession,
    since_timestamp: datetime,
) -> Dict[str, List[LoggerConfigState]]:
    """
    Return all LoggerConfigState rows since the given timestamp,
    grouped by logger_id (or logger name if available) and ordered newest-first,
    with Logger and LoggerConfig relationships loaded.
    """

    stmt = (
        select(LoggerConfigState)
        .options(
            joinedload(LoggerConfigState.logger),
            joinedload(LoggerConfigState.config),
        )
        .where(LoggerConfigState.timestamp >= since_timestamp)
        .order_by(LoggerConfigState.logger_id, desc(LoggerConfigState.timestamp))
    )

    result = await session.execute(stmt)
    states = result.scalars().all()

    grouped: Dict[str, List[LoggerConfigState]] = {}

    for state in states:
        key = state.logger.name if state.logger else state.logger_id
        grouped.setdefault(key, []).append(state)

    return grouped


async def create_or_update_logger_config_state(
    session: AsyncSession,
    *,
    config_id: str,
    logger_id: Optional[str] = None,
    running: Optional[bool] = None,
    failed: Optional[bool] = None,
    pid: Optional[int] = None,
    errors: Optional[str] = None,
) -> LoggerConfigState:
    """
    Create or update the LoggerConfigState.

    Rules:
    - One state per config when logger_id is NULL
    - One state per (logger_id, config_id) when logger_id is set
    """

    # Fetch existing state
    stmt = select(LoggerConfigState).where(
        LoggerConfigState.config_id == config_id,
        LoggerConfigState.logger_id == logger_id,
    )

    result = await session.execute(stmt)
    state = result.scalars().first()

    if state is None:
        state = LoggerConfigState(
            config_id=config_id,
            logger_id=logger_id,
            running=running,
            failed=failed if failed is not None else False,
            pid=pid,
            errors=errors,
        )
        session.add(state)
    else:
        if running is not None:
            state.running = running
        if failed is not None:
            state.failed = failed
        if pid is not None:
            state.pid = pid
        if errors is not None:
            state.errors = errors

    await session.commit()
    await session.refresh(state)
    return state


# -------------------
# DELETE
# -------------------

async def delete_logger_config_state(
    session: AsyncSession,
    state_id: int,
) -> None:
    state = await get_logger_config_state(session, state_id)
    if not state:
        raise NoResultFound("LoggerConfigState not found")

    await session.delete(state)
    await session.commit()

# -------------------
# HELPER
# -------------------

def reformat_status_by_timestamp_with_names(
    states: list[LoggerConfigState]
) -> Dict[datetime, Dict[str, Dict[str, Any]]]:
    """
    Reformat LoggerConfigState data into:
    {
        <timestamp>: {
            <logger_name>: {
                config: <config_name>,
                running: <running>
            }
        }
    }

    For states with no logger, uses "config:<config_name>" as the key.
    """
    reformatted: Dict[datetime, Dict[str, Dict[str, Any]]] = {}

    for state in states:
        ts = state.timestamp
        # Handle logger-less states
        logger_name = state.logger.name if state.logger else f"config:{state.config.name}"
        config_name = state.config.name if state.config else state.config_id

        reformatted.setdefault(ts, {})[logger_name] = {
            "config": config_name,
            "running": state.running,
            "failed": state.failed,
            "pid": state.pid,
            "errors": state.errors.split('\n'),
        }

    return reformatted
