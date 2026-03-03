from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPBearer, OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.apikeys import get_apikey_by_header, get_permissions_for_apikey
from app.db.users import get_user_by_username
from app.models import User
from app.utils import verify_password

SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token", auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
jwt_scheme = HTTPBearer(auto_error=False)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenWithRefresh(Token):
    refresh_token: str


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None
    roles: Optional[List[str]] = None


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> Optional[User]:
    user = await get_user_by_username(session, username)
    if user and verify_password(password, user.hashed_password) and not user.disabled:
        return user
    return None


def create_access_jwt(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_jwt(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def jwt_required(required_roles: Optional[Tuple[str, ...]] = None):
    """Require a valid JWT, optionally restricted to specific roles."""
    from app.deps import get_current_user

    async def role_checker(user: User = Depends(get_current_user)):
        if not user.roles or len(user.roles) == 0:
            raise HTTPException(status_code=403, detail="User has no roles assigned")

        if required_roles:
            user_role_names = {role.name for role in user.roles}
            if not user_role_names.intersection(required_roles):
                raise HTTPException(status_code=403, detail="Insufficient role")

        return user

    return role_checker


def apikey_required(route: str | None = None, method: str | None = None):
    from app.deps import get_async_session

    async def apikey_checker(
        request: Request,
        session: AsyncSession = Depends(get_async_session),
        apikey_header: str = Security(api_key_scheme),
    ):
        if not apikey_header:
            raise HTTPException(status_code=401, detail="Missing API key")

        apikey = await get_apikey_by_header(session, apikey_header)
        if not apikey or not apikey.is_active:
            raise HTTPException(status_code=403, detail="Invalid or revoked API key")

        route_path = route or request.scope["route"].path
        http_method = (method or request.method).upper()

        apikey_perms = await get_permissions_for_apikey(session, apikey.id)
        has_perm = any(
            perm.route == route_path and perm.method == http_method
            for perm in apikey_perms
        )
        if not has_perm:
            raise HTTPException(status_code=403, detail="Not authorized for this route")

        return apikey

    return apikey_checker


def apikey_or_jwt_required(
    route: Optional[str] = None,
    method: Optional[str] = None,
    required_roles: Optional[Tuple[str, ...]] = None,
):
    from app.deps import get_async_session, get_current_user_optional

    async def apikey_or_jwt_checker(
        request: Request,
        session: AsyncSession = Depends(get_async_session),
        user: Optional[User] = Depends(get_current_user_optional),
        apikey_header: str = Security(api_key_scheme),
        token: Optional[str] = Security(jwt_scheme),
    ):
        route_path = route or request.scope["route"].path
        http_method = (method or request.method).upper()

        # Reject if both provided
        if user and apikey_header:
            raise HTTPException(
                status_code=400,
                detail="Provide either JWT or API key, not both",
            )

        # --- JWT path ---
        if user:
            if not user.roles:
                raise HTTPException(
                    status_code=403, detail="User has no roles assigned"
                )

            if required_roles:
                user_role_names = {role.name for role in user.roles}
                if not user_role_names.intersection(required_roles):
                    raise HTTPException(status_code=403, detail="Insufficient role")

            return {"auth_type": "jwt", "principal": user}

        # --- API key path ---
        if apikey_header:
            apikey = await get_apikey_by_header(session, apikey_header)
            if not apikey or not apikey.is_active:
                raise HTTPException(
                    status_code=403, detail="Invalid or revoked API key"
                )

            perms = await get_permissions_for_apikey(session, apikey.id)
            has_perm = any(
                perm.route == route_path and perm.method == http_method
                for perm in perms
            )
            if not has_perm:
                raise HTTPException(
                    status_code=403, detail="Not authorized for this route"
                )

            return {"auth_type": "apikey", "principal": apikey}

        # --- Neither ---
        raise HTTPException(status_code=401, detail="No authentication provided")

    return apikey_or_jwt_checker
