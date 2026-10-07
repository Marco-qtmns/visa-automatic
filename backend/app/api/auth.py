from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, update
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
)
from ..authorization import Permission, enforce_permission, require_permission
from ..database import get_session
from ..models.auth import AuthSession, MfaChallenge, SecurityEvent, User, UserRole
from ..schemas import auth as schemas
from ..services.audit import application_audit_events, record_audit


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


def _active_session_count(user: User, now: datetime) -> int:
    return sum(
        item.revoked_at is None and as_utc(item.expires_at) > now
        for item in user.sessions
    )


def _admin_user_read(user: User) -> schemas.UserAdminRead:
    return schemas.UserAdminRead.model_validate(user).model_copy(
        update={"active_session_count": _active_session_count(user, datetime.now(timezone.utc))}
    )


def _revoke_access(
    session: Session, user: User, now: datetime, *, invalidate_challenges: bool = True
) -> int:
    revoked = session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .values(revoked_at=now)
    ).rowcount
    if invalidate_challenges:
        session.execute(
            update(MfaChallenge)
            .where(MfaChallenge.user_id == user.id, MfaChallenge.consumed_at.is_(None))
            .values(consumed_at=now)
        )
    return revoked


def _locked_active_admin_ids(session: Session) -> list:
    return list(session.scalars(
        select(User.id)
        .where(User.role == UserRole.ADMIN.value, User.is_active.is_(True))
        .with_for_update()
    ))


@router.get("/users", response_model=list[schemas.UserAdminRead])
def list_users(
    _admin: User = Depends(require_permission(Permission.USER_READ)),
    session: Session = Depends(get_session),
):
    users = session.scalars(select(User).order_by(User.created_at, User.id)).unique().all()
    return [_admin_user_read(user) for user in users]


@router.post("/users", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def add_user(payload: schemas.UserCreate, admin: User = Depends(require_permission(Permission.USER_CREATE)), session: Session = Depends(get_session)):
    try:
        user = create_user(
            session,
            email=str(payload.email),
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
            commit=False,
        )
        record_audit(
            session, actor=admin, action="USER_CREATED", target_entity_type="USER",
            target_entity_id=user.id, metadata={"role": user.role},
        )
        session.commit()
        session.refresh(user)
        return user
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.patch("/users/{user_id}", response_model=schemas.UserAdminRead)
def update_user(
    user_id: uuid.UUID,
    payload: schemas.UserUpdate,
    admin: User = Depends(require_permission(Permission.USER_EDIT)),
    session: Session = Depends(get_session),
):
    target = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if payload.is_active is False:
        enforce_permission(admin, Permission.USER_DEACTIVATE)
        if target.id == admin.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You cannot deactivate your own account.")
    if payload.role is not None and payload.role != target.role:
        enforce_permission(admin, Permission.USER_ROLE_CHANGE)

    removes_active_admin = target.is_active and target.role == UserRole.ADMIN.value and (
        payload.is_active is False or (payload.role is not None and payload.role != UserRole.ADMIN.value)
    )
    if removes_active_admin and len(_locked_active_admin_ids(session)) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The last active administrator cannot be removed.")

    old_role, old_active = target.role, target.is_active
    if payload.display_name is not None:
        target.display_name = payload.display_name.strip()
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    revoked = _revoke_access(session, target, datetime.now(timezone.utc)) if old_active and not target.is_active else 0
    if old_role != target.role:
        record_audit(
            session, actor=admin, action="USER_ROLE_CHANGED", target_entity_type="USER",
            target_entity_id=target.id, metadata={"old_role": old_role, "new_role": target.role},
        )
    if old_active != target.is_active:
        record_audit(
            session, actor=admin,
            action="USER_ACTIVATED" if target.is_active else "USER_DEACTIVATED",
            target_entity_type="USER", target_entity_id=target.id,
            metadata={"is_active": target.is_active, "revoked_sessions": revoked},
        )
    if old_role == target.role and old_active == target.is_active:
        record_audit(
            session, actor=admin, action="USER_UPDATED", target_entity_type="USER",
            target_entity_id=target.id,
        )
    session.commit()
    session.refresh(target)
    return _admin_user_read(target)


@router.post("/users/{user_id}/sessions/revoke", response_model=schemas.AdminActionRead)
def revoke_user_sessions(
    user_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.USER_SESSION_REVOKE)),
    session: Session = Depends(get_session),
):
    target = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    revoked = _revoke_access(
        session, target, datetime.now(timezone.utc), invalidate_challenges=False
    )
    record_audit(
        session, actor=admin, action="SESSIONS_REVOKED", target_entity_type="USER",
        target_entity_id=target.id, metadata={"revoked_sessions": revoked, "self": target.id == admin.id},
    )
    session.commit()
    return schemas.AdminActionRead(user_id=target.id, revoked_sessions=revoked)


@router.post("/users/{user_id}/mfa/reset", response_model=schemas.AdminActionRead)
def reset_user_mfa(
    user_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.USER_MFA_RESET)),
    session: Session = Depends(get_session),
):
    target = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    revoked = _revoke_access(session, target, datetime.now(timezone.utc))
    target.mfa_enabled = False
    target.mfa_secret_encrypted = None
    record_audit(
        session, actor=admin, action="MFA_RESET", target_entity_type="USER",
        target_entity_id=target.id, metadata={"revoked_sessions": revoked, "self": target.id == admin.id},
    )
    session.commit()
    return schemas.AdminActionRead(user_id=target.id, revoked_sessions=revoked)


@router.get("/audit-events", response_model=list[schemas.AuditEventRead])
def list_security_audit_events(
    _admin: User = Depends(require_permission(Permission.AUDIT_READ)),
    session: Session = Depends(get_session),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    fetch_count = offset + limit
    application_rows = application_audit_events(session, limit=fetch_count)
    security = session.scalars(
        select(SecurityEvent).order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc()).limit(fetch_count)
    ).all()
    user_ids = {item.user_id for item in security if item.user_id is not None} | {
        item.actor_user_id for item in application_rows if item.actor_user_id is not None
    }
    users = {item.id: item for item in session.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    application = [schemas.AuditEventRead.model_validate(item).model_copy(update={
        "actor_display_name": users[item.actor_user_id].display_name if users.get(item.actor_user_id) else None,
        "actor_email": users[item.actor_user_id].email if users.get(item.actor_user_id) else None,
    }) for item in application_rows]
    normalized_security = [schemas.AuditEventRead(
        id=item.id,
        created_at=item.created_at,
        actor_user_id=item.user_id,
        actor_role=users[item.user_id].role if users.get(item.user_id) else None,
        actor_display_name=users[item.user_id].display_name if users.get(item.user_id) else None,
        actor_email=users[item.user_id].email if users.get(item.user_id) else None,
        action=item.event_type.upper(),
        target_entity_type="AUTH_SECURITY",
        target_entity_id=str(item.user_id) if item.user_id else None,
        case_id=None,
        outcome="FAILURE" if "failed" in item.event_type else "SUCCESS",
        metadata_json={},
    ) for item in security]
    return sorted(
        application + normalized_security,
        key=lambda item: (item.created_at.isoformat(), str(item.id)),
        reverse=True,
    )[offset:offset + limit]
