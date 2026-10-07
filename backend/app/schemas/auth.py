from __future__ import annotations

import uuid
from datetime import datetime
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


class UserAdminRead(UserRead):
    created_at: datetime
    last_successful_login_at: datetime | None
    active_session_count: int = 0


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Literal["ADMIN", "CASE_WORKER", "REVIEWER"] | None = None
    is_active: bool | None = None


class AdminActionRead(BaseModel):
    status: Literal["ok"] = "ok"
    user_id: uuid.UUID
    revoked_sessions: int = 0


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    actor_display_name: str | None = None
    actor_email: str | None = None
    action: str
    target_entity_type: str
    target_entity_id: str | None
    case_id: uuid.UUID | None
    outcome: str
    metadata_json: dict
