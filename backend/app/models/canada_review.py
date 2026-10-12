from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .core import JSON_TYPE, utcnow


class CanadaTrvReviewImport(Base):
    __tablename__ = "canada_trv_review_imports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    schema_id: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(24), nullable=False)
    variant_id: Mapped[str] = mapped_column(String(40), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_headers_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    imported_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    applications: Mapped[list["CanadaTrvReviewApplication"]] = relationship(
        back_populates="import_batch", cascade="all, delete-orphan"
    )


class CanadaTrvReviewApplication(Base):
    __tablename__ = "canada_trv_review_applications"
    __table_args__ = (
        UniqueConstraint("import_id", "import_row_number", name="uq_canada_trv_review_import_row"),
        Index("ix_canada_trv_review_case_created", "case_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canada_trv_review_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    import_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_values_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    normalized_data_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    validation_issues_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    section_reviews_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="in_progress")
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    import_batch: Mapped[CanadaTrvReviewImport] = relationship(back_populates="applications")
    fields: Mapped[list["CanadaTrvReviewField"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="CanadaTrvReviewField.source_csv_column_1based"
    )


class CanadaTrvReviewField(Base):
    __tablename__ = "canada_trv_review_fields"
    __table_args__ = (
        UniqueConstraint("application_id", "field_id", name="uq_canada_trv_review_field"),
        Index("ix_canada_trv_review_field_section", "application_id", "section_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canada_trv_review_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_id: Mapped[str] = mapped_column(String(16), nullable=False)
    section_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_path: Mapped[str] = mapped_column(String(255), nullable=False)
    source_csv_column_1based: Mapped[int | None] = mapped_column(Integer)
    source_header: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_value_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    edited_value_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    applicability: Mapped[str] = mapped_column(String(24), nullable=False)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence: Mapped[str | None] = mapped_column(String(80))
    requirement_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    application: Mapped[CanadaTrvReviewApplication] = relationship(back_populates="fields")
    revisions: Mapped[list["CanadaTrvReviewRevision"]] = relationship(
        back_populates="field", cascade="all, delete-orphan", order_by="CanadaTrvReviewRevision.created_at"
    )


class CanadaTrvReviewRevision(Base):
    __tablename__ = "canada_trv_review_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canada_trv_review_fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_value_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    new_value_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    field: Mapped[CanadaTrvReviewField] = relationship(back_populates="revisions")
