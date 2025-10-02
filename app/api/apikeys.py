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
from app.schemas import APIKeyCreateSchema, APIKeyReadSchema, APIKeyRevealSchema
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

    apikey = APIKey(user_id=user.id, key_hash=key_hash, name=payload.name)
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


@router.post("/{key_id}/reissue", response_model=APIKeyReadSchema)
async def reissue_apikey(
    key_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    user_id = cast_uuid(user.id)

    result = await session.execute(
        select(APIKey).filter_by(id=cast_uuid(key_id), user_id=user_id)
    )
    old_key = result.scalar_one_or_none()

    if not old_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if not old_key.revoked:
        raise HTTPException(
            status_code=400, detail="Key must be revoked before reissuing"
        )

    raw_key = secrets.token_urlsafe(32)
    key_hash = get_apikey_hash(raw_key)

    new_key = APIKey(
        user_id=user_id,
        key_hash=key_hash,
        name=old_key.name,
        allowed_routes=[
            APIKeyPermission(route=perm.route, method=perm.method)
            for perm in old_key.allowed_routes
        ],
    )
    session.add(new_key)
    await session.commit()
    await session.refresh(new_key)

    return {
        "id": new_key.id,
        "name": new_key.name,
        "key": raw_key,  # only shown once
        "created_at": new_key.created_at,
    }
