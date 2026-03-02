# app/schemas.py
from datetime import datetime
from typing import List, Optional

from pydantic import UUID4, BaseModel, EmailStr, Field, field_serializer


class RoleSchema(BaseModel):
    id: UUID4
    name: str

    model_config = {"from_attributes": True, "extra": "ignore"}


class ProfileSchema(BaseModel):
    id: UUID4
    username: str
    full_name: str
    email: EmailStr
    roles: List[RoleSchema]  # keep full Role objects internally

    model_config = {"from_attributes": True, "extra": "ignore"}

    @field_serializer("roles")
    def serialize_roles(self, roles_value, info):
        # roles_value is already the list of RoleSchema objects
        return [r.name for r in roles_value]

    # @property
    # def role_names(self) -> List[str]:
    #     return [r.name for r in self.roles]


class ProfileUpdateSchema(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None

    model_config = {
        "from_attributes": True,  # enables ORM object parsing in Pydantic v2
    }


class ProfileUpdatePasswordSchema(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class RefreshTokenSchema(BaseModel):
    token: str
    user_id: UUID4
    issued_at: datetime
    expires_at: datetime

    model_config = {
        "from_attributes": True,  # enables ORM object parsing in Pydantic v2
    }


class RegisterUserSchema(BaseModel):
    username: str
    full_name: Optional[str] = None
    email: EmailStr
    password: str

    model_config = {
        "from_attributes": True,  # enables ORM object parsing in Pydantic v2
    }


class UserSchema(BaseModel):
    id: UUID4
    username: str
    full_name: Optional[str]
    email: EmailStr
    disabled: bool
    roles: List[RoleSchema]  # list of role names

    model_config = {
        "from_attributes": True,  # enables ORM object parsing in Pydantic v2
    }

    @property
    def role_names(self) -> List[str]:
        return [r.name for r in self.roles]


class ResetPasswordSchema(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


# --------------- API Keys --------------- #
class APIKeyReadPermissionSchema(BaseModel):
    route: str
    method: str

    model_config = {
        "from_attributes": True,  # enables ORM object parsing in Pydantic v2
    }


class APIKeyCreateSchema(BaseModel):
    name: Optional[str]
    permissions: List[APIKeyReadPermissionSchema]
    expires_at: Optional[datetime]


class APIKeyReadSchema(BaseModel):
    id: UUID4
    name: Optional[str]
    created_at: datetime
    last_used: Optional[datetime]
    expires_at: Optional[datetime]
    usage_count: int
    revoked: bool

    model_config = {
        "from_attributes": True,  # enables ORM object parsing in Pydantic v2
    }


class APIKeyRevealSchema(APIKeyReadSchema):
    unhashed_key: str


class APIKeyUpdateSchema(BaseModel):
    expires_at: Optional[datetime]
