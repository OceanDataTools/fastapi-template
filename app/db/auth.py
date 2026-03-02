from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken


async def create_refresh_token(
    session: AsyncSession, token: str, user_id: str | UUID, expires_at: datetime
):
    if isinstance(user_id, UUID):
        user_id = str(user_id)

    rt = RefreshToken(
        token=str(token),
        user_id=user_id,
        issued_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )
    session.add(rt)
    await session.commit()
    return rt


async def get_refresh_token(session: AsyncSession, token: str) -> RefreshToken | None:
    token = str(token)

    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token == token)
    )

    return result.scalars().first()


async def revoke_refresh_token(
    session: AsyncSession, token: str | None = None, user_id: str | UUID | None = None
):
    """
    Revoke a single token or all tokens for a user.
    Either `token` or `user_id` must be provided.
    """
    if token is not None:
        token = str(token)
        rt = await get_refresh_token(session, token)
        if rt:
            await session.delete(rt)
            await session.commit()
            return True

    elif user_id is not None:
        if isinstance(user_id, UUID):
            user_id = str(user_id)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        tokens = result.scalars().all()
        for rt in tokens:
            await session.delete(rt)
        await session.commit()
        return True

    return False
