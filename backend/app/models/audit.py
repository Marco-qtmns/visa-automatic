from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ApplicationAuditEvent(Base):
    """Durable application audit record. Rows are immutable after insertion."""

    __tablename__ = "application_audit_events"
    __table_args__ = (
        Index("ix_application_audit_events_case_created", "case_id", "created_at"),
        Index("ix_application_audit_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_users.id", ondelete="SET NULL")
    )
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[str | None] = mapped_column(String(64))
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL")
    )
    outcome: Mapped[str] = mapped_column(String(24), default="SUCCESS", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))


def _immutable_audit_row(*_args, **_kwargs) -> None:
    raise RuntimeError("application audit events are append-only")


event.listen(ApplicationAuditEvent, "before_update", _immutable_audit_row)
event.listen(ApplicationAuditEvent, "before_delete", _immutable_audit_row)
