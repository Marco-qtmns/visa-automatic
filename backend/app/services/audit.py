from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ..models.audit import ApplicationAuditEvent
from ..models.auth import User


SENSITIVE_AUDIT_KEYS = frozenset({
    "password", "password_hash", "mfa_secret", "mfa_secret_encrypted",
    "pending_secret_encrypted", "totp", "totp_code", "code", "token",
    "token_hash", "session_token", "csrf_token", "csrf_token_hash",
    "challenge_token", "enrollment_secret", "provisioning_uri",
})
AUDIT_INTENTS_KEY = "application_audit_intents"


def _validate_safe_metadata(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in SENSITIVE_AUDIT_KEYS:
                raise ValueError(f"sensitive audit metadata key is forbidden: {key}")
            _validate_safe_metadata(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _validate_safe_metadata(nested)


def record_audit(
    session: Session,
    *,
    actor: User | None,
    action: str,
    target_entity_type: str,
    target_entity_id: uuid.UUID | str | None = None,
    case_id: uuid.UUID | None = None,
    outcome: str = "SUCCESS",
    metadata: dict | None = None,
    request_id: str | None = None,
) -> ApplicationAuditEvent:
    safe_metadata = metadata or {}
    _validate_safe_metadata(safe_metadata)
    normalized_case_id = uuid.UUID(str(case_id)) if case_id is not None else None
    row = ApplicationAuditEvent(
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        target_entity_type=target_entity_type,
        target_entity_id=str(target_entity_id) if target_entity_id is not None else None,
        case_id=normalized_case_id,
        outcome=outcome,
        metadata_json=safe_metadata,
        request_id=request_id,
    )
    session.add(row)
    return row


def queue_audit(session: Session, **values) -> None:
    """Queue an audit row for insertion by the next commit on this Session."""
    _validate_safe_metadata(values.get("metadata") or {})
    session.info.setdefault(AUDIT_INTENTS_KEY, []).append(values)


@event.listens_for(Session, "before_commit")
def _persist_queued_audits(session: Session) -> None:
    for values in session.info.pop(AUDIT_INTENTS_KEY, []):
        record_audit(session, **values)


@event.listens_for(Session, "after_rollback")
def _discard_queued_audits(session: Session) -> None:
    session.info.pop(AUDIT_INTENTS_KEY, None)


def case_audit_events(session: Session, case_id: uuid.UUID) -> list[ApplicationAuditEvent]:
    return list(session.scalars(
        select(ApplicationAuditEvent)
        .where(ApplicationAuditEvent.case_id == case_id)
        .order_by(ApplicationAuditEvent.created_at.desc(), ApplicationAuditEvent.id.desc())
    ))


def application_audit_events(session: Session, *, limit: int = 200) -> list[ApplicationAuditEvent]:
    return list(session.scalars(
        select(ApplicationAuditEvent)
        .order_by(ApplicationAuditEvent.created_at.desc(), ApplicationAuditEvent.id.desc())
        .limit(limit)
    ))
