import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    TokenWithRefresh,
    authenticate_user,
    create_access_jwt,
    create_refresh_jwt,
    get_db,
)
from app.config import settings
from app.db.auth import create_refresh_token, get_refresh_token, revoke_refresh_token
from app.models import PasswordResetToken, User
from app.schemas import ForgotPasswordSchema, RegisterUserSchema, ResetPasswordSchema
from app.utils import cast_uuid, get_password_hash, send_reset_email

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.post("/register", status_code=201)
async def register_user(
    user: RegisterUserSchema, session: AsyncSession = Depends(get_db)
):
    result = await session.execute(select(User).where(User.username == user.username))

    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        full_name=user.full_name,
        email=user.email or "",
        hashed_password=hashed_password,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return {
        "username": new_user.username,
        "full_name": new_user.full_name,
        "email": new_user.email,
    }


@router.post("/token", response_model=TokenWithRefresh)
async def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    refresh_token_expires = timedelta(days=settings.refresh_token_expire_days)

    # Convert roles to list of strings
    role_names = [role.name for role in user.roles]

    access_token = create_access_jwt(
        data={"sub": user.username, "roles": role_names},
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_jwt(
        data={"sub": user.username, "roles": role_names},
        expires_delta=refresh_token_expires,
    )

    # Store refresh token in DB
    await revoke_refresh_token(
        session, user.id
    )  # revoke old tokens for user if you want
    await session.commit()
    await create_refresh_token(
        session,
        refresh_token,
        user.id,
        datetime.now(timezone.utc) + refresh_token_expires,
    )

    # Set refresh token cookie (HttpOnly, secure in prod)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=int(refresh_token_expires.total_seconds()),
        samesite="strict",
        secure=(settings.environment == "Production"),
        path="/",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=TokenWithRefresh)
async def refresh_access_token(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    try:
        payload = jwt.decode(refresh_token, settings.secret_key, algorithms=["HS256"])
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        roles: list[str] = payload.get("roles", [])

        if token_type != "refresh" or username is None or not isinstance(roles, list):
            raise HTTPException(
                status_code=401,
                detail="Invalid token: incorrect type, missing user, or roles",
            )

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Check token exists in DB
    rt = await get_refresh_token(session, refresh_token)
    if not rt:
        raise HTTPException(status_code=401, detail="Token revoked or invalid")

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_jwt(
        data={"sub": username, "roles": roles},
        expires_delta=access_token_expires,
    )

    max_age = max(0, int((rt.expires_at - datetime.now(timezone.utc)).total_seconds()))

    # Optionally rotate refresh token (issue new, revoke old)
    # For now, just re-set same refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=max_age,
        samesite="strict",
        secure=(settings.environment == "Production"),  # True in prod
        path="/",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await revoke_refresh_token(session, refresh_token)

    # Clear refresh token cookie
    response.delete_cookie("refresh_token", path="/")

    return {"msg": "Successfully logged out"}


@router.post("/forgot-password")
async def forgot_password(
    form_data: ForgotPasswordSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(User).where(User.email == form_data.email))
    user = result.scalar_one_or_none()

    # Always respond with 200 for security
    if not user:
        return {"message": "If this email exists, a reset link has been sent."}

    # Generate reset token
    token = str(uuid.uuid4())
    reset_token = PasswordResetToken(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(reset_token)
    await session.commit()

    # Send email in background
    background_tasks.add_task(send_reset_email, user.email, token)

    return {"message": "If this email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordSchema, session: AsyncSession = Depends(get_db)
):
    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == data.token)
    )
    token_obj = result.scalar_one_or_none()

    if (
        not token_obj
        or token_obj.used
        or token_obj.expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token."
        )

    user_result = await session.execute(
        select(User).where(User.id == cast_uuid(token_obj.user_id))
    )
    user = user_result.scalar_one()

    # Update password
    user.hashed_password = get_password_hash(data.new_password)
    token_obj.used = True

    await session.commit()

    return {"message": "Password successfully updated."}
