from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models
from ..models import canada as cm


OPERATIONAL_ROLE_VALUES = tuple(role.value for role in cm.OperationalRole)
_LEGACY_FAMILY_ROLES = {"family_member", "spouse", "former_spouse", "parent", "child"}


def normalize_legacy_roles(values: object) -> list[str]:
    """Normalize the persisted compatibility projection without losing a person."""
    source = values if isinstance(values, list) else []
    normalized: list[str] = []
    for value in source:
        role = str(value)
        if role in _LEGACY_FAMILY_ROLES:
            role = cm.OperationalRole.OTHER.value
        if role in OPERATIONAL_ROLE_VALUES and role not in normalized:
            normalized.append(role)
    return normalized or [cm.OperationalRole.OTHER.value]


def authoritative_roles(session: Session, person: models.Person) -> list[str]:
    rows = list(session.scalars(
        select(cm.CasePersonRole.role)
        .where(cm.CasePersonRole.person_id == person.id)
        .order_by(cm.CasePersonRole.assigned_at, cm.CasePersonRole.id)
    ))
    return list(dict.fromkeys(str(role) for role in rows)) or normalize_legacy_roles(person.roles)


def refresh_role_projection(session: Session, person: models.Person) -> models.Person:
    person.roles = authoritative_roles(session, person)
    return person


def set_authoritative_roles(
    session: Session,
    person: models.Person,
    roles: list[str | cm.OperationalRole],
    *,
    assigned_by: str | None = None,
) -> None:
    values = list(dict.fromkeys(cm.OperationalRole(role).value for role in roles))
    if not values:
        raise ValueError("a person must have at least one operational role")
    session.execute(delete(cm.CasePersonRole).where(cm.CasePersonRole.person_id == person.id))
    session.add_all([
        cm.CasePersonRole(
            case_id=person.case_id,
            person_id=person.id,
            role=role,
            assigned_by=assigned_by,
        )
        for role in values
    ])
    person.roles = values


def add_authoritative_role(
    session: Session,
    person: models.Person,
    role: str | cm.OperationalRole,
    *,
    assigned_by: str | None = None,
) -> cm.CasePersonRole:
    value = cm.OperationalRole(role).value
    rows = list(session.scalars(select(cm.CasePersonRole).where(
        cm.CasePersonRole.person_id == person.id
    )))
    if not rows:
        rows = [
            cm.CasePersonRole(
                case_id=person.case_id,
                person_id=person.id,
                role=legacy_role,
                assigned_by=assigned_by,
            )
            for legacy_role in normalize_legacy_roles(person.roles)
        ]
        session.add_all(rows)
        session.flush()
    if value != cm.OperationalRole.OTHER.value:
        for row in list(rows):
            if row.role == cm.OperationalRole.OTHER.value:
                session.delete(row)
                rows.remove(row)
        session.flush()
    existing = next((row for row in rows if row.role == value), None)
    if existing is None:
        existing = session.scalar(select(cm.CasePersonRole).where(
            cm.CasePersonRole.person_id == person.id,
            cm.CasePersonRole.role == value,
        ))
    if existing is None:
        existing = cm.CasePersonRole(
            case_id=person.case_id,
            person_id=person.id,
            role=value,
            assigned_by=assigned_by,
        )
        session.add(existing)
    elif assigned_by is not None:
        existing.assigned_by = assigned_by
    session.flush()
    person.roles = authoritative_roles(session, person)
    return existing
