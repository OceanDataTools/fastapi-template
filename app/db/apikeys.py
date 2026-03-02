from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIKey, APIKeyPermission
from app.utils import get_apikey_hash


async def get_apikey_by_header(session: AsyncSession, apikey: str) -> APIKey | None:
    result = await session.execute(
        select(APIKey).where(APIKey.key_hash == get_apikey_hash(apikey))
    )

    return result.scalar_one_or_none()


async def add_permissions_to_apikey(
    session: AsyncSession,
    apikey_id: UUID,
    permissions: list[
        tuple[str, str]
    ],  # e.g., [("/position/", "POST"), ("/map/", "GET")]
):
    for route, method in permissions:
        perm = APIKeyPermission(apikey_id=apikey_id, route=route, method=method.upper())
        session.add(perm)
    await session.commit()


async def get_permissions_for_apikey(session: AsyncSession, apikey_id: UUID):
    result = await session.execute(
        select(APIKeyPermission).where(APIKeyPermission.apikey_id == apikey_id)
    )

    return result.scalars().all()
