from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class ChallengeRequest(BaseModel):
    challenge_token: str = Field(min_length=32, max_length=256)
    code: str = Field(pattern=r"^[0-9]{6}$")


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    mfa_enabled: bool


class LoginChallengeRead(BaseModel):
    status: Literal["mfa_required", "mfa_enrollment_required"]
    challenge_token: str
    expires_in_seconds: int
    enrollment_secret: str | None = None
    provisioning_uri: str | None = None


class AuthenticatedRead(BaseModel):
    status: Literal["authenticated"] = "authenticated"
    user: UserRead
    csrf_token: str


class CurrentUserRead(BaseModel):
    user: UserRead


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str
    role: Literal["ADMIN", "CASE_WORKER", "REVIEWER"]
