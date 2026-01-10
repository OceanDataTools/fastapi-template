from typing import Optional
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_openrvdas import Cruise


async def get_cruise(session: AsyncSession) -> Optional[Cruise]:
    """
    Retrieve the single Cruise record, if it exists.
    """
    result = await session.execute(select(Cruise))
    return result.scalars().first()


async def create_or_update_cruise(
    session: AsyncSession,
    cruise_id: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    config_filename: Optional[str] = None,
    config_text: Optional[str] = None,
) -> Cruise:
    """
    Upsert the single Cruise record.
    Validates that start <= end if both are provided.
    """
    # Validate business rule
    if start is not None and end is not None and start > end:
        raise ValueError(f"Cruise start time ({start}) cannot be after end time ({end})")

    # Fetch existing cruise
    result = await session.execute(select(Cruise))
    cruise = result.scalars().first()

    if cruise is None:
        cruise = Cruise(
            id=cruise_id,
            start=start,
            end=end,
            config_filename=config_filename,
            config_text=config_text,
        )
        session.add(cruise)
    else:
        cruise.id = cruise_id
        if start is not None:
            cruise.start = start
        if end is not None:
            cruise.end = end
        if config_filename is not None:
            cruise.config_filename = config_filename
        if config_text is not None:
            cruise.config_text = config_text

    await session.commit()
    await session.refresh(cruise)
    return cruise


async def delete_cruise(session: AsyncSession) -> None:
    """
    Delete the single Cruise record, if it exists.
    """
    result = await session.execute(select(Cruise))
    cruise = result.scalars().first()

    if cruise is None:
        raise NoResultFound("No Cruise record found to delete.")

    await session.delete(cruise)
    await session.commit()
