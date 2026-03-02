from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# -------------------
# Declarative base
# -------------------
class Base(DeclarativeBase):
    pass


# -------------------
# Association table (many-to-many)
# -------------------
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        String(36),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# -------------------
# Role
# -------------------
class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    users: Mapped[list["User"]] = relationship(
        "User", secondary=user_roles, back_populates="roles", lazy="selectin"
    )

    def __repr__(self):
        return f"<Role(name={self.name})>"


# -------------------
# User
# -------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()), index=True
    )
    username: Mapped[str] = mapped_column(
        String(150), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    roles: Mapped[list[Role]] = relationship(
        "Role", secondary=user_roles, back_populates="users", lazy="selectin"
    )
    apikeys: Mapped[list["APIKey"]] = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        role_names = [role.name for role in self.roles]
        return (
            f"<User(username={self.username}, email={self.email}, roles={role_names})>"
        )


# -------------------
# APIKey
# -------------------
class APIKey(Base):
    __tablename__ = "apikeys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User", back_populates="apikeys")
    allowed_routes: Mapped[list["APIKeyPermission"]] = relationship(
        "APIKeyPermission", back_populates="api_key", cascade="all, delete-orphan"
    )

    @property
    def is_expired(self) -> bool:
        """Returns True if the key is past expiration."""
        return (
            self.expires_at is not None
            and datetime.now(timezone.utc) >= self.expires_at
        )

    @property
    def is_active(self) -> bool:
        """True if not revoked and not expired."""
        return not self.revoked and not self.is_expired


# -------------------
# APIKeyPermission
# -------------------
class APIKeyPermission(Base):
    __tablename__ = "apikey_permissions"

    apikey_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("apikeys.id", ondelete="CASCADE"), primary_key=True
    )
    route: Mapped[str] = mapped_column(String, primary_key=True)
    method: Mapped[str] = mapped_column(String, primary_key=True)

    api_key: Mapped["APIKey"] = relationship("APIKey", back_populates="allowed_routes")


# -------------------
# PasswordResetToken
# -------------------
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc) + timedelta(hours=1),
    )
    used: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User", back_populates="reset_tokens")


# -------------------
# RefreshToken
# -------------------
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    token: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")

    def __repr__(self):
        return f"<RefreshToken(token={self.token}, user_id={self.user_id})>"
