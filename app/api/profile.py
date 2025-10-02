from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.db.session import get_async_session
from app.db.users import update_user
from app.models import User
from app.schemas import ProfileSchema, ProfileUpdatePasswordSchema, ProfileUpdateSchema
from app.utils import cast_uuid, get_password_hash, verify_password

router = APIRouter(prefix="/api/v1/profile", tags=["Profile"])

# @router.get("/profile")
# async def get_platforms(session: AsyncSession = Depends(get_async_session)):
#  return await fetch_platforms(session)


@router.get("", response_model=ProfileSchema)
async def read_profile(
    session: AsyncSession = Depends(get_async_session),
    current_user=Depends(get_current_user),
):
    result = await session.execute(
        select(User).options(selectinload(User.roles)).where(User.id == current_user.id)
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.patch("", response_model=ProfileSchema)
async def update_profile(
    payload: ProfileUpdateSchema,
    session: AsyncSession = Depends(get_async_session),
    current_user=Depends(get_current_user),
):
    updated_user = await update_user(
        session, user_id=cast_uuid(current_user.id), **payload.dict()
    )
    return updated_user


@router.post("/change-password", status_code=204)
async def change_password(
    payload: ProfileUpdatePasswordSchema,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    # Re-fetch user in the current session to ensure attachment
    result = await session.execute(
        select(User).where(User.id == cast_uuid(current_user.id))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Step 1: Verify current password
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )

    # Step 2: Hash and update to new password
    user.hashed_password = get_password_hash(payload.new_password)
    await session.commit()

    return  # 204 No Content
