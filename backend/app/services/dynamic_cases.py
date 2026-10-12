from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import models
from ..models import canada as cm
from ..schemas import core as schemas
from .canada_preparation import CanadaPreparationReadinessService
from .core import DomainNotFound, DomainValidationError
from .person_roles import add_authoritative_role
from .requirements import RequirementEngine


FACT_FIELDS = frozenset({
    "sponsor.exists", "host.exists", "trip.payer", "destination.country_code",
    "commercial.instructions", "special.circumstances", "additional.notes",
})
BOOLEAN_FIELDS = frozenset({"sponsor.exists", "host.exists"})
TEXT_FIELDS = frozenset({
    "case.visa_type", "applicant.given_names", "applicant.family_name",
    "contact.email", "contact.phone", "trip.purpose", "destination.country_code",
    "commercial.instructions", "special.circumstances", "additional.notes",
})
PERSON_REFERENCE_FIELDS = frozenset({"sponsor.person_id", "host.person_id"})


class CanonicalDecisionService:
    """Writes manual/provider decisions to typed authority plus an immutable revision ledger."""

    def __init__(self, session: Session):
        self.session = session

    def apply(self, case_id: uuid.UUID, payload: schemas.CanonicalDecisionBatch):
        case = self.session.get(models.Case, case_id)
        if case is None:
            raise DomainNotFound("Case not found")
        decisions = {item.field_path: item.value_json for item in payload.decisions}
        if len(decisions) != len(payload.decisions):
            raise DomainValidationError("each canonical field may appear only once per decision batch")
        self._validate(decisions)
        for item in payload.decisions:
            current_revision = self.session.scalar(select(func.max(models.CanonicalValueRevision.revision)).where(
                models.CanonicalValueRevision.case_id == case_id,
                models.CanonicalValueRevision.field_path == item.field_path,
            )) or 0
            if item.expected_revision != current_revision:
                raise DomainValidationError(
                    f"stale canonical value for {item.field_path}; reload the Case before saving"
                )
        applicant = self._applicant(case_id)
        if applicant is not None and self.session.scalar(select(cm.CasePersonRole.id).where(
            cm.CasePersonRole.case_id == case_id,
            cm.CasePersonRole.person_id == applicant.id,
            cm.CasePersonRole.role == cm.OperationalRole.APPLICANT,
        )) is None:
            add_authoritative_role(
                self.session, applicant, cm.OperationalRole.APPLICANT,
                assigned_by=payload.reviewed_by,
            )
        if applicant is None and any(
            path.startswith(("applicant.", "contact.")) or path == "trip.purpose"
            for path in decisions
        ):
            given = decisions.get("applicant.given_names")
            family = decisions.get("applicant.family_name")
            if not isinstance(given, str) or not given.strip() or not isinstance(family, str) or not family.strip():
                raise DomainValidationError(
                    "given and family names are required when creating the canonical applicant"
                )
            applicant = models.Person(
                case_id=case_id, first_name=given.strip(), last_name=family.strip(), roles=["applicant"]
            )
            self.session.add(applicant)
            self.session.flush()
            add_authoritative_role(
                self.session, applicant, cm.OperationalRole.APPLICANT,
                assigned_by=payload.reviewed_by,
            )
        app = self._application(case_id, applicant)
        now = datetime.now(timezone.utc)
        revisions = []
        try:
            for field_path, value in decisions.items():
                old_value, entity_type, entity_id = self._write(
                    case, app, applicant, field_path, value, payload
                )
                item = self.append_revision(
                    case_id=case_id, field_path=field_path, entity_type=entity_type,
                    entity_id=entity_id, original_value=old_value, value=value,
                    source_type=payload.source_type,
                    source_reference=payload.source_reference,
                    source_timestamp=payload.source_timestamp,
                    source_version=payload.source_version,
                    review_state="needs_review" if value is None else (
                        "confirmed" if old_value in (None, "") or old_value == value else "corrected"
                    ), reviewed_by=payload.reviewed_by, reviewed_at=now,
                )
                revisions.append(item)
            self.session.flush()
            RequirementEngine(self.session).evaluate(case_id)
        except Exception:
            self.session.rollback()
            raise
        for item in revisions:
            self.session.refresh(item)
        return revisions

    def append_revision(
        self, *, case_id, field_path, entity_type, entity_id, original_value, value,
        source_type, source_reference, review_state, reviewed_by,
        source_timestamp=None, source_version=None, reviewed_at=None,
    ):
        revision = (self.session.scalar(select(func.max(models.CanonicalValueRevision.revision)).where(
            models.CanonicalValueRevision.case_id == case_id,
            models.CanonicalValueRevision.field_path == field_path,
        )) or 0) + 1
        item = models.CanonicalValueRevision(
            case_id=case_id, field_path=field_path, entity_type=entity_type,
            entity_id=entity_id, revision=revision,
            original_value_json=original_value, value_json=value,
            source_type=source_type, source_reference=source_reference,
            source_timestamp=source_timestamp, source_version=source_version,
            review_state=review_state, reviewed_by=reviewed_by,
            reviewed_at=reviewed_at or datetime.now(timezone.utc),
        )
        self.session.add(item)
        return item

    def _validate(self, decisions: dict[str, Any]) -> None:
        for path, value in decisions.items():
            if path in BOOLEAN_FIELDS and value is not None and not isinstance(value, bool):
                raise DomainValidationError(f"{path} must be yes, no, or unknown")
            if path == "trip.payer" and value is not None and value not in {"applicant", "sponsor", "other", "mixed"}:
                raise DomainValidationError("trip.payer must be applicant, sponsor, other, mixed, or unknown")
            if path in TEXT_FIELDS and value is not None and (not isinstance(value, str) or not value.strip()):
                raise DomainValidationError(f"{path} must be non-empty text or unknown")
            if path == "destination.country_code" and value is not None and len(value.strip()) not in {2, 3}:
                raise DomainValidationError("destination country must be an ISO alpha-2 or alpha-3 code")
            if path in PERSON_REFERENCE_FIELDS and value is not None:
                try:
                    uuid.UUID(str(value))
                except (TypeError, ValueError):
                    raise DomainValidationError(f"{path} must identify a person in this case") from None

    def _applicant(self, case_id):
        role = self.session.scalar(select(cm.CasePersonRole).where(
            cm.CasePersonRole.case_id == case_id,
            cm.CasePersonRole.role == cm.OperationalRole.APPLICANT,
        ))
        if role:
            return self.session.get(models.Person, role.person_id)
        app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        return self.session.get(models.Person, app.applicant_person_id) if app and app.applicant_person_id else None

    def _application(self, case_id, applicant):
        app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        if app is None and applicant is not None:
            app = cm.CanadaApplication(case_id=case_id, applicant_person_id=applicant.id)
            self.session.add(app)
            self.session.flush()
        elif app is not None and app.applicant_person_id is None and applicant is not None:
            app.applicant_person_id = applicant.id
        return app

    def _write(self, case, app, applicant, path, value, payload):
        if path == "case.visa_type":
            old = case.visa_type
            case.visa_type = value.strip()
            return old, "case", case.id
        if path in {"applicant.given_names", "applicant.family_name"}:
            if applicant is None:
                raise DomainValidationError("canonical applicant is unavailable")
            attr = "first_name" if path.endswith("given_names") else "last_name"
            old = getattr(applicant, attr)
            setattr(applicant, attr, value.strip())
            return old, "person", applicant.id
        if path in {"contact.email", "contact.phone"}:
            if applicant is None:
                raise DomainValidationError("canonical applicant is unavailable")
            contact_type = path.rsplit(".", 1)[1]
            contact = self.session.scalar(select(cm.ContactPoint).where(
                cm.ContactPoint.person_id == applicant.id,
                cm.ContactPoint.type == contact_type,
                cm.ContactPoint.is_primary.is_(True),
            ))
            old = contact.value if contact else None
            if value is None:
                if contact is not None:
                    self.session.delete(contact)
                return old, "contact", contact.id if contact else None
            if contact is None:
                contact = cm.ContactPoint(
                    person_id=applicant.id, type=contact_type, value=value.strip(),
                    purpose="primary", is_primary=True, sort_order=0,
                )
                self.session.add(contact)
                self.session.flush()
            else:
                contact.value = value.strip()
            return old, "contact", contact.id
        if path == "trip.purpose":
            if app is None:
                raise DomainValidationError("canonical application is unavailable")
            trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
            if trip is None:
                trip = cm.TripPlan(application_id=app.id)
                self.session.add(trip)
                self.session.flush()
            old = trip.intake_purpose_text
            trip.intake_purpose_text = value.strip() if value is not None else None
            trip.purpose_review_state = "confirmed" if value is not None else "needs_review"
            case.purpose = value.strip()[:128] if value is not None else "To be confirmed"
            return old, "trip_plan", trip.id
        if path in PERSON_REFERENCE_FIELDS:
            if app is None:
                raise DomainValidationError("canonical application is unavailable")
            person = self.session.get(models.Person, uuid.UUID(str(value))) if value is not None else None
            if person is not None and person.case_id != case.id:
                raise DomainValidationError(f"{path} must identify a person in this case")
            if value is not None and person is None:
                raise DomainValidationError(f"{path} must identify a person in this case")
            trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id))
            if trip is None:
                trip = cm.TripPlan(application_id=app.id)
                self.session.add(trip)
                self.session.flush()
            role = cm.OperationalRole.SPONSOR if path.startswith("sponsor.") else cm.OperationalRole.HOST
            if role == cm.OperationalRole.SPONSOR:
                current = self.session.scalar(select(cm.FundingSource).where(
                    cm.FundingSource.trip_plan_id == trip.id,
                    cm.FundingSource.payer_kind == "sponsor",
                    cm.FundingSource.is_primary.is_(True),
                ))
                old = current.person_id if current else None
                for item in self.session.scalars(select(cm.FundingSource).where(
                    cm.FundingSource.trip_plan_id == trip.id,
                    cm.FundingSource.payer_kind == "sponsor",
                )):
                    self.session.delete(item)
                if person is not None:
                    self.session.add(cm.FundingSource(
                        trip_plan_id=trip.id, payer_kind="sponsor", person_id=person.id,
                        is_primary=True, sort_order=0,
                    ))
            else:
                current = self.session.scalar(select(cm.HostRecord).where(
                    cm.HostRecord.trip_plan_id == trip.id,
                    cm.HostRecord.is_primary.is_(True),
                ))
                old = current.person_id if current and current.host_type == "person" else None
                for item in self.session.scalars(select(cm.HostRecord).where(cm.HostRecord.trip_plan_id == trip.id)):
                    self.session.delete(item)
                if person is not None:
                    self.session.add(cm.HostRecord(
                        trip_plan_id=trip.id, host_type="person", person_id=person.id,
                        is_primary=True, sort_order=0,
                    ))
            affected = list(self.session.scalars(select(models.Person).where(models.Person.case_id == case.id)))
            self.session.execute(delete(cm.CasePersonRole).where(
                cm.CasePersonRole.case_id == case.id, cm.CasePersonRole.role == role,
            ))
            if person is not None:
                add_authoritative_role(self.session, person, role, assigned_by=payload.reviewed_by)
            for affected_person in affected:
                roles = list(self.session.scalars(select(cm.CasePersonRole.role).where(
                    cm.CasePersonRole.person_id == affected_person.id
                )))
                affected_person.roles = list(dict.fromkeys(roles)) or [cm.OperationalRole.OTHER.value]
            return str(old) if old else None, "person", person.id if person else None
        if path in FACT_FIELDS:
            current = self.session.scalar(select(models.Fact).where(
                models.Fact.case_id == case.id,
                models.Fact.key == path,
                models.Fact.status == "confirmed",
            ).order_by(models.Fact.created_at.desc(), models.Fact.id.desc()))
            old = current.value_json if current else None
            for fact in self.session.scalars(select(models.Fact).where(
                models.Fact.case_id == case.id,
                models.Fact.key == path,
                models.Fact.status == "confirmed",
            )):
                fact.status = "rejected"
            fact = models.Fact(
                case_id=case.id, person_id=None, key=path, value_json=value,
                source_type={
                    "employee_manual": "manual",
                    "commercial_message": "whatsapp",
                    "google_forms_csv": "google_form",
                }[payload.source_type],
                source_reference=payload.source_reference,
                confidence=1.0 if value is not None else None,
                status="confirmed" if value is not None else "proposed",
            )
            self.session.add(fact)
            self.session.flush()
            return old, "fact", fact.id
        raise DomainValidationError(f"unsupported canonical field: {path}")

    def list_revisions(self, case_id):
        if self.session.get(models.Case, case_id) is None:
            raise DomainNotFound("Case not found")
        return list(self.session.scalars(select(models.CanonicalValueRevision).where(
            models.CanonicalValueRevision.case_id == case_id
        ).order_by(models.CanonicalValueRevision.created_at.desc(), models.CanonicalValueRevision.id.desc())))


class DynamicCaseService:
    def __init__(self, session: Session):
        self.session = session

    def status(self, case_id: uuid.UUID) -> dict[str, Any]:
        case = self.session.get(models.Case, case_id)
        if case is None:
            raise DomainNotFound("Case not found")
        readiness = CanadaPreparationReadinessService(self.session).evaluate(case_id)
        issues: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(issue_key, category, code, field_path, severity, title, message, action, source_type, source_id=None):
            if issue_key in seen:
                return
            seen.add(issue_key)
            issues.append({
                "issue_key": issue_key, "category": category, "code": code,
                "field_path": field_path, "severity": severity, "title": title,
                "message": message, "action": action, "source_type": source_type,
                "source_id": source_id,
            })

        for item in readiness.issues:
            add(f"readiness:{item.code}:{item.path}", "canonical", item.code, item.path,
                item.severity, item.label, item.message, item.action, "readiness")
        for item in self.session.scalars(select(models.FactExtractionCandidate).where(
            models.FactExtractionCandidate.case_id == case_id,
            models.FactExtractionCandidate.status.in_((models.FactCandidateStatus.PROPOSED, models.FactCandidateStatus.CONFLICT)),
        )):
            add(f"fact-candidate:{item.id}", "evidence", "unresolved_candidate", item.key,
                "blocking" if item.status == models.FactCandidateStatus.CONFLICT else "warning",
                f"Review {item.key}", "Commercial message evidence awaits review.",
                "Confirm, correct, or reject the candidate.", "commercial_message", item.id)
        for item in self.session.scalars(select(models.Task).where(
            models.Task.case_id == case_id, models.Task.status.in_(("open", "in_progress"))
        )):
            add(f"task:{item.id}", "task", "open_task", None,
                "blocking" if item.blocking else "warning", item.title, item.description,
                "Complete or resolve the task.", "task", item.id)
        for key, label in (("sponsor.exists", "Financial sponsor"), ("host.exists", "Host in Canada")):
            if self._fact(case_id, key) is None:
                add(f"decision:{key}", "decision", "unresolved_decision", key, "blocking",
                    label, f"{label} is unknown.", "Confirm yes or no.", "canonical")
        values = self.current_values(case_id, case)
        for exists_key, person_key, label in (
            ("sponsor.exists", "sponsor.person_id", "Sponsor identity"),
            ("host.exists", "host.person_id", "Host identity"),
        ):
            if values.get(exists_key) is True and values.get(person_key) is None:
                add(f"decision:{person_key}", "decision", "missing_party_identity", person_key, "blocking",
                    label, f"{label} is not selected.", "Select the known person.", "canonical")

        pending_documents = list(self.session.scalars(select(models.Requirement).where(
            models.Requirement.case_id == case_id, models.Requirement.active.is_(True),
            models.Requirement.is_blocking.is_(True),
            models.Requirement.fulfillment_status == models.RequirementFulfillmentStatus.PENDING,
        )))
        conflicts = [item for item in issues if item["severity"] == "blocking"]
        has_activity = bool(
            case.workflow_state != models.WorkflowState.INTAKE
            or self.session.scalar(select(func.count(models.Person.id)).where(models.Person.case_id == case_id))
            or self.session.scalar(select(func.count(models.Fact.id)).where(models.Fact.case_id == case_id))
            or self.session.scalar(select(func.count(models.Document.id)).where(models.Document.case_id == case_id))
            or self.session.scalar(select(func.count(models.ConversationImport.id)).where(models.ConversationImport.case_id == case_id))
            or self.session.scalar(select(func.count(cm.CanadaLegacyImportRun.id)).where(cm.CanadaLegacyImportRun.case_id == case_id))
        )
        stage = {
            models.WorkflowState.REVIEW: "FINAL_REVIEW",
            models.WorkflowState.READY: "READY",
            models.WorkflowState.SUBMITTED: "SUBMITTED",
        }.get(case.workflow_state, "ACTIVE" if has_activity else "NEW")
        intake_ready = bool(values.get("case.visa_type") and values.get("applicant.given_names")
                            and values.get("applicant.family_name") and values.get("trip.purpose")
                            and values.get("destination.country_code") and values.get("trip.payer")
                            and values.get("sponsor.exists") is not None and values.get("host.exists") is not None
                            and (values.get("sponsor.exists") is not True or values.get("sponsor.person_id"))
                            and (values.get("host.exists") is not True or values.get("host.person_id")))
        return {
            "case_id": case_id, "lifecycle_stage": stage,
            "legacy_workflow_state": case.workflow_state,
            "can_enter_final_review": readiness.ready and not conflicts,
            "canonical_values": values,
            "dimensions": [
                {"key": "intake", "ready": intake_ready, "blocking_count": 0 if intake_ready else 1, "warning_count": 0},
                {"key": "canonical", "ready": readiness.blocking_count == 0, "blocking_count": readiness.blocking_count, "warning_count": readiness.warning_count},
                {"key": "documents", "ready": not pending_documents, "blocking_count": len(pending_documents), "warning_count": 0},
                {"key": "issues", "ready": not conflicts, "blocking_count": len(conflicts), "warning_count": len(issues) - len(conflicts)},
            ],
            "issues": issues,
        }

    def _fact(self, case_id, key):
        return self.session.scalar(select(models.Fact).where(
            models.Fact.case_id == case_id, models.Fact.key == key,
            models.Fact.status == "confirmed",
        ).order_by(models.Fact.created_at.desc(), models.Fact.id.desc()))

    def current_values(self, case_id, case=None):
        case = case or self.session.get(models.Case, case_id)
        app = self.session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case_id))
        applicant = self.session.get(models.Person, app.applicant_person_id) if app and app.applicant_person_id else None
        trip = self.session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == app.id)) if app else None
        contacts = {}
        if applicant:
            for item in self.session.scalars(select(cm.ContactPoint).where(
                cm.ContactPoint.person_id == applicant.id, cm.ContactPoint.is_primary.is_(True)
            )):
                contacts[item.type] = item.value
        values = {
            "case.visa_type": case.visa_type,
            "applicant.given_names": applicant.first_name if applicant else None,
            "applicant.family_name": applicant.last_name if applicant else None,
            "contact.email": contacts.get("email"), "contact.phone": contacts.get("phone"),
            "trip.purpose": trip.intake_purpose_text if trip else None,
        }
        funding = self.session.scalar(select(cm.FundingSource).where(
            cm.FundingSource.trip_plan_id == trip.id,
            cm.FundingSource.payer_kind == "sponsor",
            cm.FundingSource.is_primary.is_(True),
        )) if trip else None
        host = self.session.scalar(select(cm.HostRecord).where(
            cm.HostRecord.trip_plan_id == trip.id, cm.HostRecord.is_primary.is_(True),
        )) if trip else None
        values["sponsor.person_id"] = str(funding.person_id) if funding and funding.person_id else None
        values["host.person_id"] = str(host.person_id) if host and host.host_type == "person" and host.person_id else None
        for key in FACT_FIELDS:
            fact = self._fact(case_id, key)
            values[key] = fact.value_json if fact else None
        return values
