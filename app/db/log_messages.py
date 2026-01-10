from typing import Optional, List
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_openrvdas import LogMessage


async def get_log_message(session: AsyncSession, log_id: int) -> Optional[LogMessage]:
    """
    Retrieve a single LogMessage by primary key.
    """
    result = await session.execute(select(LogMessage).where(LogMessage.id == log_id))
    return result.scalars().first()


async def get_log_messages(
    session: AsyncSession,
    source: Optional[str] = None,
    user: Optional[str] = None,
    log_level: Optional[int] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> List[LogMessage]:
    """
    Retrieve LogMessage records with optional filtering.
    """
    stmt = select(LogMessage)

    if source is not None:
        stmt = stmt.where(LogMessage.source == source)
    if user is not None:
        stmt = stmt.where(LogMessage.user == user)
    if log_level is not None:
        stmt = stmt.where(LogMessage.log_level == log_level)
    if since is not None:
        stmt = stmt.where(LogMessage.timestamp >= since)
    if until is not None:
        stmt = stmt.where(LogMessage.timestamp <= until)
    if limit is not None:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt.order_by(LogMessage.timestamp.desc()))
    return list(result.scalars().all())


async def create_log_message(
    session: AsyncSession,
    source: Optional[str] = None,
    user: Optional[str] = None,
    log_level: Optional[int] = 0,
    message: Optional[str] = None,
) -> LogMessage:
    """
    Create a new LogMessage record.
    """
    log = LogMessage(
        source=source,
        user=user,
        log_level=log_level,
        message=message,
    )

    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def delete_log_message(session: AsyncSession, log_id: int) -> None:
    """
    Delete a single LogMessage by primary key.
    """
    result = await session.execute(select(LogMessage).where(LogMessage.id == log_id))
    log = result.scalars().first()

    if log is None:
        raise NoResultFound(f"No LogMessage found with id={log_id}")

    await session.delete(log)
    await session.commit()


async def delete_all_log_messages(session: AsyncSession) -> int:
    """
    Delete all LogMessage records. Returns number of rows deleted.
    """
    result = await session.execute(select(LogMessage))
    logs = result.scalars().all()

    if not logs:
        raise NoResultFound("No LogMessage records found to delete.")

    count = len(logs)
    for log in logs:
        await session.delete(log)

    await session.commit()
    return count
