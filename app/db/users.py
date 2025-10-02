from typing import List, Optional, Union

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Role, User
from app.utils import cast_uuid, get_password_hash


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    result = await session.execute(
        select(User).options(selectinload(User.roles)).where(User.username == username)
    )

    return result.scalars().first()


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    result = await session.execute(
        select(User).options(selectinload(User.roles)).where(User.email == email)
    )

    return result.scalars().first()


async def create_user(
    session: AsyncSession,
    username: str,
    full_name: str,
    email: str,
    hashed_password: str,
    roles: Union[str, List[str]] = "user",
) -> User:
    # Normalize to list
    role_names = [roles] if isinstance(roles, str) else roles

    # Fetch Role objects
    result = await session.execute(select(Role).where(Role.name.in_(role_names)))

    role_objs = result.scalars().all()

    if len(role_objs) != len(role_names):
        missing = set(role_names) - {r.name for r in role_objs}
        raise ValueError(f"Roles not found: {missing}")

    user = User(
        username=username,
        full_name=full_name,
        email=email,
        hashed_password=hashed_password,
        roles=role_objs,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    user_id: str,  # matches User.id type
    username: Optional[str] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    roles: Optional[Union[str, List[str]]] = None,
) -> User:
    user_id = cast_uuid(user_id)

    result = await session.execute(select(User).where(User.id == user_id))

    user = result.scalar_one_or_none()

    if user is None:
        raise NoResultFound(f"User with id {user_id} not found")

    if username is not None:
        user.username = username
    if full_name is not None:
        user.full_name = full_name
    if email is not None:
        user.email = email
    if password is not None:
        user.hashed_password = get_password_hash(password)
    if roles is not None:
        role_names = [roles] if isinstance(roles, str) else roles
        result = await session.execute(select(Role).where(Role.name.in_(role_names)))
        role_objs = result.scalars().all()
        if len(role_objs) != len(role_names):
            missing = set(role_names) - {r.name for r in role_objs}
            raise ValueError(f"Roles not found: {missing}")
        user.roles = role_objs

    await session.commit()
    await session.refresh(user)
    return user
