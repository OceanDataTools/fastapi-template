from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt

# from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.apikeys import get_apikey_by_header, get_permissions_for_apikey
from app.db.session import AsyncSessionLocal
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


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> Optional[User]:
    user = await get_user_by_username(session, username)
    if user and verify_password(password, user.hashed_password) and not user.disabled:
        return user
    return None


def create_access_jwt(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_jwt(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await get_user_by_username(session, username)
    if user is None:
        raise credentials_exception
    if user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


async def get_current_user_optional(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> Optional[User]:

    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            return None
    except JWTError:
        return None

    user = await get_user_by_username(session, username)
    if not user or user.disabled:
        return None
    return user


def jwt_required(required_roles: Optional[Tuple[str, ...]] = None):
    """
    Require the user to have at least one of the specified roles.
    """

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
    async def apikey_checker(
        request: Request,
        session: AsyncSession = Depends(get_db),
        apikey_header: str = Security(api_key_scheme),
    ):
        if not apikey_header:
            raise HTTPException(status_code=401, detail="Missing API key")

        apikey = await get_apikey_by_header(session, apikey_header)
        if not apikey or not apikey.is_active:
            raise HTTPException(status_code=403, detail="Invalid or revoked API key")

        route_path = route or request.scope["route"].path
        http_method = (method or request.method).upper()

        # Check permission
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
    async def apikey_or_jwt_checker(
        request: Request,
        session: AsyncSession = Depends(get_db),
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

        # --- Neither JWT nor API key ---
        raise HTTPException(status_code=401, detail="No authentication provided")

    return apikey_or_jwt_checker
