from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .core import utcnow


INTAKE_STATUSES = "'RECEIVED', 'PROCESSING', 'PROCESSED', 'NEEDS_REVIEW', 'FAILED'"
ATTEMPT_STATUSES = "'PROCESSING', 'PROCESSED', 'NEEDS_REVIEW', 'FAILED'"


class IntakeSubmission(Base):
    __tablename__ = "intake_submissions"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_hash", "mapping_version",
            name="uq_intake_source_hash_mapping",
        ),
        Index(
            "uq_intake_external_mapping", "source_type", "source_external_id", "mapping_version",
            unique=True,
            postgresql_where=text("source_external_id IS NOT NULL"),
            sqlite_where=text("source_external_id IS NOT NULL"),
        ),
        Index("ix_intake_status_received", "processing_status", "received_at"),
        CheckConstraint(f"processing_status IN ({INTAKE_STATUSES})", name="intake_status_valid"),
        CheckConstraint("duplicate_receive_count >= 0", name="intake_duplicate_count_nonnegative"),
        CheckConstraint("retry_count >= 0", name="intake_retry_count_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_external_id: Mapped[str | None] = mapped_column(String(255))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_source_reference: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(24), default="RECEIVED", nullable=False)
    requested_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), index=True)
    import_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canada_legacy_import_runs.id", ondelete="SET NULL"))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    issue_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_receive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class IntakeProcessingAttempt(Base):
    __tablename__ = "intake_processing_attempts"
    __table_args__ = (
        UniqueConstraint("submission_id", "attempt_number", name="uq_intake_attempt_number"),
        CheckConstraint(f"status IN ({ATTEMPT_STATUSES})", name="intake_attempt_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("intake_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PROCESSING", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    import_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canada_legacy_import_runs.id", ondelete="SET NULL"))
    created_case: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_existing_case: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
