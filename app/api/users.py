from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.db.users import get_user_by_email, get_user_by_username

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("/available")
async def check_user_availability(
    username: Optional[str] = Query(None, min_length=3, max_length=30),
    email: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_async_session),
):
    if not username and not email:
        raise HTTPException(
            status_code=400, detail="Either username or email must be provided"
        )

    if username:
        user = await get_user_by_username(session, username)
    elif email:
        user = await get_user_by_email(session, email)
    else:
        user = None  # This won't be reached, but makes type checkers happy

    return {"available": user is None}
