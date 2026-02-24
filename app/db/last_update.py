from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import LastUpdate

async def touch_last_update(session: AsyncSession):
    result = await session.execute(
        select(LastUpdate).order_by(LastUpdate.timestamp.desc()).limit(1)
    )
    last = result.scalar_one_or_none()

    if last is None:
        last = LastUpdate()
        session.add(last)
    else:
        # touching it is enough; onupdate will bump timestamp
        session.add(last)

    await session.commit()
