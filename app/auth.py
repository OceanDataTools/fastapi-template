from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Union

import jwt
from fastapi import Depends, HTTPException, Request, Security, WebSocket, status
from fastapi.security import APIKeyHeader, HTTPBearer, OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.apikeys import get_apikey_by_header, get_permissions_for_apikey
from app.db.users import get_user_by_username
from app.models import APIKey, User
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


# ---------------------------------------------------------------------------
# WebSocket authentication
# ---------------------------------------------------------------------------

# Pseudo-method stored in APIKeyPermission.method for WebSocket routes, which
# have no HTTP method of their own.
WEBSOCKET_METHOD = "WEBSOCKET"


def accepts_apikey(endpoint):
    """Mark a WebSocket endpoint as accepting API keys.

    Marked endpoints are listed by GET /api/v1/apikeys/routes with the
    WEBSOCKET method, so keys can be granted access to them. Apply it below
    the @router.websocket(...) decorator.
    """
    endpoint.accepts_apikey = True
    return endpoint


async def authenticate_websocket(
    websocket: WebSocket,
    route: str,
    allow_apikey: bool = False,
) -> Optional[Union[User, APIKey]]:
    """Authenticate a WebSocket handshake before it is accepted.

    Browsers can't set headers on a WebSocket, so credentials are taken from
    the query string as well as from headers:

      JWT access token:  ?token=<jwt>      or  Authorization: Bearer <jwt>
      API key:           ?api_key=<key>    or  X-API-Key: <key>

    A JWT must be an access (not refresh) token for a user who still exists,
    isn't disabled and has at least one role. An API key (only when
    allow_apikey is True) must be active, belong to an enabled user, and
    carry a (route, WEBSOCKET) permission.

    Returns the authenticated User or APIKey. On failure, closes the socket
    with WS_1008_POLICY_VIOLATION and returns None; the caller should then
    simply return.
    """
    from app.db.session import AsyncSessionLocal

    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            token = credentials.strip()

    apikey_value = websocket.query_params.get("api_key") or websocket.headers.get(
        "x-api-key"
    )

    principal: Optional[Union[User, APIKey]] = None

    # Exactly one credential is accepted; API keys only where allowed.
    if token and not apikey_value:
        principal = await _authenticate_websocket_jwt(AsyncSessionLocal, token)
    elif apikey_value and not token and allow_apikey:
        principal = await _authenticate_websocket_apikey(
            AsyncSessionLocal, apikey_value, route
        )

    if principal is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return principal


async def _authenticate_websocket_jwt(session_factory, token: str) -> Optional[User]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    username = payload.get("sub")
    if not username or payload.get("type") == "refresh":
        return None

    async with session_factory() as session:
        user = await get_user_by_username(session, username)

    if user is None or user.disabled or not user.roles:
        return None
    return user


async def _authenticate_websocket_apikey(
    session_factory, apikey_value: str, route: str
) -> Optional[APIKey]:
    async with session_factory() as session:
        apikey = await get_apikey_by_header(session, apikey_value)
        if apikey is None or not apikey.is_active:
            return None

        owner = await session.get(User, apikey.user_id)
        if owner is None or owner.disabled:
            return None

        perms = await get_permissions_for_apikey(session, apikey.id)

    if not any(
        perm.route == route and perm.method == WEBSOCKET_METHOD for perm in perms
    ):
        return None
    return apikey
