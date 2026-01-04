# routers/apikeys.py
import secrets
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db.session import get_async_session
from app.models import APIKey, APIKeyPermission, User
from app.schemas import (
    APIKeyCreateSchema,
    APIKeyReadPermissionSchema,
    APIKeyReadSchema,
    APIKeyRevealSchema,
    APIKeyUpdateSchema,
)
from app.utils import cast_uuid, get_apikey_hash

router = APIRouter(prefix="/api/v1/apikeys", tags=["API Keys"])


@router.get("", response_model=List[APIKeyReadSchema])
async def list_apikeys(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(select(APIKey).filter_by(user_id=cast_uuid(user.id)))
    apikeys = result.scalars().all()
    return apikeys


@router.post("", response_model=APIKeyRevealSchema)
async def create_apikey(
    payload: APIKeyCreateSchema,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    raw_key = secrets.token_urlsafe(32)
    key_hash = get_apikey_hash(raw_key)

    apikey = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        name=payload.name,
        expires_at=payload.expires_at,
    )
    session.add(apikey)
    await session.flush()  # assigns apikey.id
    await session.refresh(apikey)  # loads DB-generated fields

    for perm in payload.permissions:
        permissions = APIKeyPermission(
            apikey_id=apikey.id, route=perm.route, method=perm.method
        )
        session.add(permissions)

    await session.commit()
    await session.refresh(apikey)

    return APIKeyRevealSchema(
        **APIKeyReadSchema.model_validate(apikey).dict(), unhashed_key=raw_key
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_apikey(
    key_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(APIKey).filter_by(id=cast_uuid(key_id), user_id=cast_uuid(user.id))
    )
    apikey = result.scalar_one_or_none()

    if not apikey:
        raise HTTPException(status_code=404, detail="API key not found")

    await session.delete(apikey)
    await session.commit()


@router.patch("/{key_id}/revoke", response_model=APIKeyReadSchema)
async def revoke_apikey(
    key_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(APIKey).filter_by(id=cast_uuid(key_id), user_id=cast_uuid(user.id))
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.revoked = not key.revoked

    await session.commit()
    await session.refresh(key)

    return key


@router.patch("/{key_id}", response_model=APIKeyReadSchema)
async def update_apikey(
    key_id: UUID,
    payload: APIKeyUpdateSchema,
    session: AsyncSession = Depends(get_async_session),
    user=Depends(get_current_user),
):
    """
    Update an API key's expiration date. Key must exist and belong to the current user.
    """
    user_id = cast_uuid(user.id)

    # Fetch the key
    result = await session.execute(
        select(APIKey).filter_by(id=cast_uuid(key_id), user_id=user_id)
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    if key.revoked:
        raise HTTPException(status_code=400, detail="Cannot update a revoked key")

    # Update expires_at
    key.expires_at = payload.expires_at
    session.add(key)
    await session.commit()
    await session.refresh(key)

    return {
        "id": key.id,
        "name": key.name,
        "created_at": key.created_at,
        "last_used": key.last_used,
        "expires_at": key.expires_at,
        "usage_count": key.usage_count,
        "revoked": key.revoked,
    }


@router.get("/{key_id}/routes", response_model=list[APIKeyReadPermissionSchema])
async def get_apikey_routes(
    key_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user=Depends(get_current_user),
):
    # Ensure the API key exists and belongs to the current user
    result = await session.execute(
        select(APIKey.id).filter_by(id=cast_uuid(key_id), user_id=cast_uuid(user.id))
    )
    apikey_id = result.scalar_one_or_none()
    if not apikey_id:
        raise HTTPException(status_code=404, detail="API key not found")

    # Query the permissions directly
    permissions_result = await session.execute(
        select(APIKeyPermission).filter_by(apikey_id=cast_uuid(key_id))
    )
    permissions = permissions_result.scalars().all()

    return permissions
