from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..models.canada_review import (
    CanadaTrvReviewApplication,
    CanadaTrvReviewField,
    CanadaTrvReviewImport,
    CanadaTrvReviewRevision,
)
from .audit import record_audit
from .canada_trv_schema import CsvParser, Normalizer, SchemaRegistry
from .core import DomainNotFound, DomainValidationError
from .requirements import RequirementEngine


FINAL_FIELD_STATES = {"confirmed", "confirmed_after_correction", "not_applicable"}
BLOCKING_SEVERITIES = {"blocking", "error"}


class CanadaTrvReviewService:
    def __init__(self, session: Session, registry: SchemaRegistry | None = None):
        self.session = session
        self.registry = registry or SchemaRegistry()

    def import_csv(
        self,
        content: bytes,
        filename: str,
        raw_source_reference: str,
        *,
        requested_case_id: uuid.UUID | None = None,
        actor=None,
    ) -> list[CanadaTrvReviewApplication]:
        parsed = CsvParser(self.registry).parse(content)
        if requested_case_id is not None and self.session.get(models.Case, requested_case_id) is None:
            raise DomainNotFound("Case not found")
        batch = CanadaTrvReviewImport(
            schema_id=self.registry.schema["schema_id"],
            schema_version=self.registry.schema["schema_version"],
            variant_id=parsed.variant_id,
            source_filename=PurePath(filename or "google-forms.csv").name[:255],
            source_hash=hashlib.sha256(content).hexdigest(),
            raw_source_reference=raw_source_reference,
            raw_headers_json=list(parsed.headers),
            imported_by=getattr(actor, "email", None),
        )
        self.session.add(batch)
        self.session.flush()
        normalizer = Normalizer(self.registry)
        applications: list[CanadaTrvReviewApplication] = []
        created_case_ids: list[uuid.UUID] = []
        for index, row in enumerate(parsed.rows, start=2):
            if index == 2 and requested_case_id:
                case_id = requested_case_id
            else:
                case_id = self._create_case(actor).id
                created_case_ids.append(case_id)
            normalized = normalizer.normalize(parsed, row, index)
            application = CanadaTrvReviewApplication(
                import_id=batch.id,
                case_id=case_id,
                import_row_number=index,
                raw_values_json=list(row),
                normalized_data_json=normalized.data,
                validation_issues_json=list(normalized.issues),
                section_reviews_json={},
                status="needs_attention" if any(item["severity"] in BLOCKING_SEVERITIES for item in normalized.issues) else "in_progress",
            )
            self.session.add(application)
            self.session.flush()
            for item in normalized.fields:
                self.session.add(CanadaTrvReviewField(
                    application_id=application.id,
                    field_id=item["field_id"], section_id=item["source_section_id"],
                    target_path=item["target_path"], source_csv_column_1based=item["source_csv_column_1based"],
                    source_header=item["source_header"], raw_value=item["raw_value"],
                    normalized_value_json=item["normalized_value"], applicability=item["applicability"],
                    review_status=item["review_status"], evidence=item["evidence"],
                    requirement_mode=item["requirement_mode"],
                ))
            applications.append(application)
            record_audit(
                self.session, actor=actor, action="CANADA_TRV_SCHEMA_REVIEW_IMPORTED",
                target_entity_type="CANADA_TRV_REVIEW", target_entity_id=application.id,
                case_id=case_id,
                metadata={"schema_version": "3.0.0", "variant_id": parsed.variant_id, "row_number": index},
            )
        self.session.commit()
        for case_id in created_case_ids:
            RequirementEngine(self.session).evaluate(case_id)
        return [self.get(item.id) for item in applications]

    def _create_case(self, actor):
        case_id = uuid.uuid4()
        year = datetime.now(timezone.utc).year
        case = models.Case(
            id=case_id, case_number=f"CA-{year}-{case_id.int % 100_000_000:08d}",
            visa_type="canada_trv", purpose="To be confirmed",
        )
        self.session.add(case)
        self.session.flush()
        record_audit(
            self.session, actor=actor, action="CASE_CREATED",
            target_entity_type="CASE", target_entity_id=case.id, case_id=case.id,
        )
        return case

    def list_for_case(self, case_id: uuid.UUID) -> list[CanadaTrvReviewApplication]:
        return list(self.session.scalars(
            select(CanadaTrvReviewApplication)
            .where(CanadaTrvReviewApplication.case_id == case_id)
            .order_by(CanadaTrvReviewApplication.created_at.desc())
        ))

    def get(self, application_id: uuid.UUID) -> CanadaTrvReviewApplication:
        value = self.session.scalar(
            select(CanadaTrvReviewApplication)
            .options(
                selectinload(CanadaTrvReviewApplication.import_batch),
                selectinload(CanadaTrvReviewApplication.fields).selectinload(CanadaTrvReviewField.revisions),
            )
            .where(CanadaTrvReviewApplication.id == application_id)
            .execution_options(populate_existing=True)
        )
        if value is None:
            raise DomainNotFound("Canada TRV review application not found")
        return value

    def update_field(self, field_id: uuid.UUID, value: Any, *, actor) -> CanadaTrvReviewField:
        field = self._field(field_id)
        if field.applicability == "not_applicable" and value in (None, ""):
            raise DomainValidationError("A non-applicable empty field does not need correction")
        definition = self._definition(field.field_id)
        raw = "" if value is None else str(value)
        normalized, issue = Normalizer._normalize_value(definition, raw)
        old = self._effective(field)
        field.edited_value_json = normalized if issue is None else raw
        field.review_status = "needs_review" if issue else "corrected_pending_confirmation"
        field.reviewer_id = None
        field.reviewed_at = None
        self.session.add(CanadaTrvReviewRevision(
            field_id=field.id, old_value_json=old, new_value_json=field.edited_value_json,
            actor_id=self._actor(actor),
        ))
        application = self.get(field.application_id)
        self._recalculate(application)
        record_audit(
            self.session, actor=actor, action="CANADA_TRV_REVIEW_FIELD_CORRECTED",
            target_entity_type="CANADA_TRV_REVIEW_FIELD", target_entity_id=field.id,
            case_id=application.case_id, metadata={"field_id": field.field_id},
        )
        self.session.commit()
        return self._field(field.id)

    def confirm_field(self, field_id: uuid.UUID, *, actor) -> CanadaTrvReviewField:
        field = self._field(field_id)
        if field.applicability != "applicable":
            raise DomainValidationError("Only applicable fields can be confirmed")
        if self._effective(field) in (None, "") and field.requirement_mode == "review_when_applicable":
            raise DomainValidationError("Enter the applicable value before confirmation")
        if field.review_status == "needs_review":
            raise DomainValidationError("Correct the invalid or unresolved value before confirmation")
        field.review_status = "confirmed_after_correction" if field.edited_value_json is not None else "confirmed"
        field.reviewer_id = self._actor(actor)
        field.reviewed_at = datetime.now(timezone.utc)
        application = self.get(field.application_id)
        self._refresh_status(application)
        record_audit(
            self.session, actor=actor, action="CANADA_TRV_REVIEW_FIELD_CONFIRMED",
            target_entity_type="CANADA_TRV_REVIEW_FIELD", target_entity_id=field.id,
            case_id=application.case_id, metadata={"field_id": field.field_id},
        )
        self.session.commit()
        return self._field(field.id)

    def confirm_section(self, application_id: uuid.UUID, section_id: str, *, actor) -> CanadaTrvReviewApplication:
        application = self.get(application_id)
        fields = [item for item in application.fields if item.section_id == section_id]
        if not fields:
            raise DomainValidationError("Unknown or empty review section")
        blocking = [item for item in application.validation_issues_json
                    if item.get("section_id") == section_id and item.get("severity") in BLOCKING_SEVERITIES]
        incomplete = [item for item in fields if item.applicability == "applicable"
                      and item.requirement_mode == "review_when_applicable"
                      and item.review_status not in {"confirmed", "confirmed_after_correction"}]
        if blocking or incomplete:
            raise DomainValidationError("Confirm every applicable field and resolve blocking issues before confirming this section")
        now, reviewer = datetime.now(timezone.utc), self._actor(actor)
        reviews = dict(application.section_reviews_json or {})
        reviews[section_id] = {"status": "confirmed", "reviewer_id": reviewer, "reviewed_at": now.isoformat()}
        application.section_reviews_json = reviews
        self._refresh_status(application)
        self.session.commit()
        return self.get(application.id)

    def confirm_application(self, application_id: uuid.UUID, *, actor) -> CanadaTrvReviewApplication:
        application = self.get(application_id)
        blockers = [item for item in application.validation_issues_json if item.get("severity") in BLOCKING_SEVERITIES]
        open_fields = [item for item in application.fields
                       if item.applicability != "not_applicable"
                       and item.requirement_mode == "review_when_applicable"
                       and item.review_status not in {"confirmed", "confirmed_after_correction"}]
        if blockers or open_fields:
            raise DomainValidationError("Resolve and confirm all applicable required review fields first")
        application.status = "confirmed"
        application.confirmed_by = self._actor(actor)
        application.confirmed_at = datetime.now(timezone.utc)
        record_audit(
            self.session, actor=actor, action="CANADA_TRV_REVIEW_CONFIRMED",
            target_entity_type="CANADA_TRV_REVIEW", target_entity_id=application.id,
            case_id=application.case_id, metadata={"schema_version": "3.0.0"},
        )
        self.session.commit()
        return self.get(application.id)

    def _recalculate(self, application: CanadaTrvReviewApplication) -> None:
        definitions = {item["field_id"]: item for item in self.registry.fields}
        raw_paths = {item.target_path: self._predicate_value(item) for item in application.fields}
        evaluator = Normalizer(self.registry).conditions
        issues = [item for item in application.validation_issues_json
                  if item.get("code") not in {"condition_conflict", "required_review_value_missing", "invalid_value"}]
        data: dict[str, Any] = {}
        for field in application.fields:
            definition = definitions[field.field_id]
            condition = definition.get("applicability", {"mode": "always"})
            result = "true" if condition.get("mode") == "always" else evaluator.evaluate(condition["condition"], raw_paths)
            effective = self._effective(field)
            if result == "false" and effective in (None, ""):
                field.applicability, field.review_status = "not_applicable", "not_applicable"
            elif result == "false":
                field.applicability, field.review_status = "not_applicable", "needs_review"
                issues.append(Normalizer._issue("condition_conflict", "error", "A value was supplied although its branch is inactive.", field.field_id, field.section_id))
            elif result == "unknown":
                field.applicability, field.review_status = "unknown", "needs_review"
            else:
                field.applicability = "applicable"
                if effective in (None, "") and field.requirement_mode == "review_when_applicable":
                    field.review_status = "missing"
                    issues.append(Normalizer._issue("required_review_value_missing", "error", "Applicable review information is missing.", field.field_id, field.section_id))
                elif field.review_status in {"not_applicable", "confirmed", "confirmed_after_correction"}:
                    field.review_status = "corrected_pending_confirmation" if field.edited_value_json is not None else "pending"
            Normalizer._set_path(data, field.target_path, effective)
        Normalizer(self.registry)._prune_repeated_arrays(data, [self._field_dict(item) for item in application.fields])
        Normalizer(self.registry)._prepare_unstructured_collections(data)
        issues.extend(Normalizer(self.registry)._cross_validate([self._field_dict(item) for item in application.fields]))
        application.normalized_data_json = data
        application.validation_issues_json = self._dedupe_issues(issues)
        reviews = dict(application.section_reviews_json or {})
        for section_id in {item.section_id for item in application.fields if item.review_status not in FINAL_FIELD_STATES}:
            reviews.pop(section_id, None)
        application.section_reviews_json = reviews
        application.confirmed_by = None
        application.confirmed_at = None
        self._refresh_status(application)

    def _refresh_status(self, application: CanadaTrvReviewApplication) -> None:
        if application.confirmed_at:
            application.status = "confirmed"
            return
        if any(item.get("severity") in BLOCKING_SEVERITIES for item in application.validation_issues_json):
            application.status = "needs_attention"
        elif any(item.review_status not in FINAL_FIELD_STATES for item in application.fields if item.requirement_mode == "review_when_applicable"):
            application.status = "in_progress"
        else:
            application.status = "ready_to_confirm"

    def _field(self, field_id: uuid.UUID) -> CanadaTrvReviewField:
        value = self.session.get(CanadaTrvReviewField, field_id)
        if value is None:
            raise DomainNotFound("Canada TRV review field not found")
        return value

    def _definition(self, field_id: str) -> dict[str, Any]:
        return next(item for item in self.registry.fields if item["field_id"] == field_id)

    @staticmethod
    def _effective(field: CanadaTrvReviewField) -> Any:
        return field.edited_value_json if field.edited_value_json is not None else field.normalized_value_json

    @staticmethod
    def _predicate_value(field: CanadaTrvReviewField) -> Any:
        if field.edited_value_json is not None:
            if isinstance(field.edited_value_json, bool):
                return "Sim" if field.edited_value_json else "Não"
            return field.edited_value_json
        return field.raw_value

    @staticmethod
    def _actor(actor) -> str:
        return str(getattr(actor, "email", None) or getattr(actor, "id", None) or "unknown")

    def _field_dict(self, field: CanadaTrvReviewField) -> dict[str, Any]:
        return {
            "field_id": field.field_id, "source_section_id": field.section_id,
            "target_path": field.target_path, "raw_value": field.raw_value,
            "normalized_value": self._effective(field), "review_status": field.review_status,
        }

    @staticmethod
    def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result, seen = [], set()
        for item in issues:
            key = (item.get("code"), item.get("field_id"), item.get("section_id"))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
