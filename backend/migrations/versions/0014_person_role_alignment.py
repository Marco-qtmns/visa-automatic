"""align Person role projection with authoritative operational roles

Revision ID: 0014_person_role_alignment
Revises: 0013_automated_intake
Create Date: 2026-10-07
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "0014_person_role_alignment"
down_revision: str | None = "0013_automated_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALID_ROLES = ("applicant", "representative", "sponsor", "host", "other")
LEGACY_FAMILY_ROLES = {"family_member", "spouse", "former_spouse", "parent", "child"}


def _normalized(values: object) -> list[str]:
    source = values if isinstance(values, list) else []
    result: list[str] = []
    for value in source:
        role = str(value)
        if role in LEGACY_FAMILY_ROLES:
            role = "other"
        if role in VALID_ROLES and role not in result:
            result.append(role)
    return result or ["other"]


def _new_id(reference: object) -> uuid.UUID | str:
    value = uuid.uuid4()
    return value if isinstance(reference, uuid.UUID) else value.hex


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("persons") or not inspector.has_table("case_person_roles"):
        return
    metadata = sa.MetaData()
    people = sa.Table("persons", metadata, autoload_with=bind)
    roles = sa.Table("case_person_roles", metadata, autoload_with=bind)

    for person in bind.execute(sa.select(people.c.id, people.c.case_id, people.c.roles)).mappings():
        existing = list(bind.execute(
            sa.select(roles.c.role).where(roles.c.person_id == person["id"])
        ).scalars())
        if not existing:
            for role in _normalized(person["roles"]):
                if role in {"applicant", "representative"}:
                    occupied = bind.execute(sa.select(roles.c.id).where(
                        roles.c.case_id == person["case_id"], roles.c.role == role
                    )).scalar_one_or_none()
                    if occupied is not None:
                        continue
                bind.execute(roles.insert().values(
                    id=_new_id(person["id"]), case_id=person["case_id"], person_id=person["id"],
                    role=role, assigned_by="migration:0014", assigned_at=datetime.now(timezone.utc),
                ))
                existing.append(role)
        projection = [role for role in VALID_ROLES if role in existing]
        if not projection:
            bind.execute(roles.insert().values(
                id=_new_id(person["id"]), case_id=person["case_id"], person_id=person["id"],
                role="other", assigned_by="migration:0014", assigned_at=datetime.now(timezone.utc),
            ))
            projection = ["other"]
        bind.execute(people.update().where(people.c.id == person["id"]).values(roles=projection))


def downgrade() -> None:
    # This corrective migration deliberately does not recreate invalid role values.
    pass
