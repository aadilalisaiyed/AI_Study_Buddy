
from uuid import UUID
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class UserCreate(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=100,
    )

    email: EmailStr

    password: str = Field(
        min_length=12,
        max_length=128,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if len(value) < 2:
            raise ValueError(
                "Name must contain at least 2 characters"
            )

        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    name: str
    email: EmailStr
    is_active: bool
    created_at: datetime
