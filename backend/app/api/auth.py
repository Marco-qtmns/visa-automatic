from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..auth import (
    SESSION_COOKIE_NAME,
    authenticated_session,
    as_utc,
    complete_mfa,
    cookie_secure,
    create_user,
    password_login,
    provisioning_uri,
    record_event,
    require_authenticated_request,
    require_admin_user,
)
from ..database import get_session
from ..models.auth import AuthSession, User
from ..schemas import auth as schemas


router = APIRouter(prefix="/auth", tags=["Authentication"])
CSRF_COOKIE_NAME = "va_csrf"


def _set_session_cookie(response: Response, raw_token: str, csrf_token: str, auth_session: AuthSession) -> None:
    max_age = max(0, int((as_utc(auth_session.expires_at) - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=max_age,
        expires=auth_session.expires_at,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        expires=auth_session.expires_at,
        path="/",
        secure=cookie_secure(),
        httponly=False,
        samesite="strict",
    )


@router.post("/login", response_model=schemas.LoginChallengeRead)
def login(payload: schemas.LoginRequest, request: Request, session: Session = Depends(get_session)):
    client_host = request.client.host if request.client else "unknown"
    user, token, challenge, secret = password_login(
        session, email=str(payload.email), password=payload.password, client_host=client_host
    )
    return schemas.LoginChallengeRead(
        status="mfa_required" if user.mfa_enabled else "mfa_enrollment_required",
        challenge_token=token,
        expires_in_seconds=300,
        enrollment_secret=secret,
        provisioning_uri=provisioning_uri(user, secret) if secret else None,
    )


@router.post("/mfa/verify", response_model=schemas.AuthenticatedRead)
def verify_mfa(payload: schemas.ChallengeRequest, response: Response, session: Session = Depends(get_session)):
    user, raw_session, csrf_token, auth_session = complete_mfa(
        session, challenge_token=payload.challenge_token, code=payload.code
    )
    _set_session_cookie(response, raw_session, csrf_token, auth_session)
    return schemas.AuthenticatedRead(user=user, csrf_token=csrf_token)


@router.get("/me", response_model=schemas.CurrentUserRead)
def me(auth_session: AuthSession = Depends(authenticated_session)):
    return {"user": auth_session.user}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, _user: User = Depends(require_authenticated_request), auth_session: AuthSession = Depends(authenticated_session), session: Session = Depends(get_session)):
    auth_session.revoked_at = datetime.now(timezone.utc)
    record_event(session, "logout", user_id=auth_session.user_id)
    record_event(session, "session_revoked", user_id=auth_session.user_id)
    session.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=cookie_secure(), httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=cookie_secure(), httponly=False, samesite="strict")


@router.post("/users", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def add_user(payload: schemas.UserCreate, _admin: User = Depends(require_admin_user), session: Session = Depends(get_session)):
    try:
        return create_user(
            session,
            email=str(payload.email),
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
