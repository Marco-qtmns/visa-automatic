from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..models.auth import User
from .audit import record_audit
from ..models import canada as cm
from ..storage import LocalStorageProvider, StorageProvider
from .core import DomainNotFound, DomainValidationError


class WorkflowTransitionError(DomainValidationError):
    def __init__(self, message: str, *, api_detail: dict | None = None):
        super().__init__(message)
        self.api_detail = api_detail


ALLOWED_TRANSITIONS: dict[models.WorkflowState, frozenset[models.WorkflowState]] = {
    models.WorkflowState.INTAKE: frozenset({models.WorkflowState.DOCUMENTS}),
    models.WorkflowState.DOCUMENTS: frozenset({
        models.WorkflowState.INTAKE,
        models.WorkflowState.PREPARE,
    }),
    models.WorkflowState.PREPARE: frozenset({
        models.WorkflowState.DOCUMENTS,
        models.WorkflowState.REVIEW,
    }),
    models.WorkflowState.REVIEW: frozenset({
        models.WorkflowState.DOCUMENTS,
        models.WorkflowState.PREPARE,
        models.WorkflowState.READY,
    }),
    models.WorkflowState.READY: frozenset({
        models.WorkflowState.DOCUMENTS,
        models.WorkflowState.PREPARE,
        models.WorkflowState.REVIEW,
        models.WorkflowState.SUBMITTED,
    }),
    models.WorkflowState.SUBMITTED: frozenset(),
}

STATE_ORDER = {
    state: index
    for index, state in enumerate(
        (
            models.WorkflowState.INTAKE,
            models.WorkflowState.DOCUMENTS,
            models.WorkflowState.PREPARE,
            models.WorkflowState.REVIEW,
            models.WorkflowState.READY,
            models.WorkflowState.SUBMITTED,
        )
    )
}


@dataclass(frozen=True)
class NextAction:
    type: str
    title: str
    case_id: uuid.UUID
    fact_id: uuid.UUID | None = None
    fact_key: str | None = None
    requirement_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    fact_candidate_id: uuid.UUID | None = None
    import_run_id: uuid.UUID | None = None
    preparation_issue_code: str | None = None
    preparation_path: str | None = None
    target_state: models.WorkflowState | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class WorkflowService:
    """Owns all workflow transitions, gates, history, and Next Action logic."""

    REQUIRED_FACTS = {
        "sponsor.exists": "Confirm whether a financial sponsor exists",
        "host.exists": "Confirm whether a host in Canada exists",
    }
    OPEN_TASK_STATUSES = {"open", "in_progress"}

    def __init__(self, session: Session, storage: StorageProvider | None = None):
        self.session = session
        self.storage = storage or LocalStorageProvider.generated_from_environment()

    def _case(self, case_id: uuid.UUID, *, for_update: bool = False) -> models.Case:
        query = select(models.Case).where(models.Case.id == case_id)
        if for_update:
            query = query.with_for_update()
        case = self.session.scalar(query)
        if case is None:
            raise DomainNotFound("Case not found")
        return case

    def get_state(self, case_id: uuid.UUID) -> models.WorkflowState:
        return self._case(case_id).workflow_state

    def history(self, case_id: uuid.UUID) -> list[models.WorkflowTransition]:
        self._case(case_id)
        return list(self.session.scalars(
            select(models.WorkflowTransition)
            .where(models.WorkflowTransition.case_id == case_id)
            .order_by(models.WorkflowTransition.created_at, models.WorkflowTransition.id)
        ))

    def allowed_targets(self, case_id: uuid.UUID) -> list[models.WorkflowState]:
        state = self.get_state(case_id)
        return sorted(ALLOWED_TRANSITIONS[state], key=STATE_ORDER.get)

    def _facts(self, case_id: uuid.UUID) -> list[models.Fact]:
        return list(self.session.scalars(
            select(models.Fact)
            .where(models.Fact.case_id == case_id)
            .order_by(models.Fact.created_at, models.Fact.id)
        ))

    def _conflicts(self, case_id: uuid.UUID) -> list[models.Fact]:
        return [fact for fact in self._facts(case_id) if fact.status == "conflict"]

    def _confirmed_fact(self, case_id: uuid.UUID, key: str) -> models.Fact | None:
        return self.session.scalar(
            select(models.Fact)
            .where(
                models.Fact.case_id == case_id,
                models.Fact.key == key,
                models.Fact.status == "confirmed",
            )
            .order_by(models.Fact.created_at.desc(), models.Fact.id.desc())
            .limit(1)
        )

    def _pending_blocking_requirements(self, case_id: uuid.UUID) -> list[models.Requirement]:
        return list(self.session.scalars(
            select(models.Requirement)
            .where(
                models.Requirement.case_id == case_id,
                models.Requirement.active.is_(True),
                models.Requirement.is_blocking.is_(True),
                models.Requirement.fulfillment_status
                == models.RequirementFulfillmentStatus.PENDING,
            )
            .order_by(models.Requirement.created_at, models.Requirement.id)
        ))

    def _open_blocking_tasks(self, case_id: uuid.UUID) -> list[models.Task]:
        return list(self.session.scalars(
            select(models.Task)
            .where(
                models.Task.case_id == case_id,
                models.Task.blocking.is_(True),
                models.Task.status.in_(self.OPEN_TASK_STATUSES),
            )
            .order_by(models.Task.created_at, models.Task.id)
        ))

    def _validate_transition(
        self,
        case: models.Case,
        target_state: models.WorkflowState,
        *,
        actor: str | None = None,
        require_actor: bool = True,
    ) -> None:
        current = case.workflow_state
        if target_state not in ALLOWED_TRANSITIONS[current]:
            raise WorkflowTransitionError(
                f"transition {current.value} -> {target_state.value} is not allowed"
            )

        is_forward = STATE_ORDER[target_state] > STATE_ORDER[current]
        if is_forward and self._conflicts(case.id):
            raise WorkflowTransitionError("unresolved fact conflicts block forward progression")

        if current == models.WorkflowState.INTAKE and target_state == models.WorkflowState.DOCUMENTS:
            if not case.visa_type.strip():
                raise WorkflowTransitionError("visa_type is required before DOCUMENTS")
            if not case.purpose.strip():
                raise WorkflowTransitionError("purpose is required before DOCUMENTS")
            missing = [key for key in self.REQUIRED_FACTS if self._confirmed_fact(case.id, key) is None]
            if missing:
                raise WorkflowTransitionError(
                    "confirmed facts required before DOCUMENTS: " + ", ".join(missing)
                )

        if current == models.WorkflowState.DOCUMENTS and target_state == models.WorkflowState.PREPARE:
            pending = self._pending_blocking_requirements(case.id)
            if pending:
                raise WorkflowTransitionError("active blocking requirements remain unresolved")

        if is_forward and self._open_blocking_tasks(case.id):
            if current == models.WorkflowState.REVIEW:
                raise WorkflowTransitionError("open blocking review tasks prevent READY")
            raise WorkflowTransitionError("open blocking tasks prevent forward progression")

        if current == models.WorkflowState.PREPARE and target_state == models.WorkflowState.REVIEW:
            from .preparation_runs import CanadaPreparationService

            readiness, current_run, integrity = CanadaPreparationService(
                self.session, self.storage
            ).current_package(case.id)
            if current_run is None:
                if not readiness.ready:
                    reasons = [item.model_dump(mode="json") for item in readiness.issues]
                else:
                    code, message, action = {
                        "no_matching_success": (
                            "current_preparation_run_required",
                            "Generate a new application package from the current canonical data.",
                            "Open preparation and generate the package again",
                        ),
                        "artifact_manifest_missing": (
                            "preparation_artifact_manifest_invalid",
                            "The generated package does not contain the complete required artifact set.",
                            "Regenerate the application package",
                        ),
                        "artifact_missing": (
                            "preparation_artifact_missing",
                            "A generated package artifact is missing from storage.",
                            "Regenerate the application package",
                        ),
                        "artifact_hash_mismatch": (
                            "preparation_artifact_integrity_failed",
                            "A generated package artifact failed its integrity check.",
                            "Regenerate the application package",
                        ),
                    }.get(integrity, (
                        "current_preparation_run_required",
                        "A current complete generated application package is required.",
                        "Open preparation and generate the package",
                    ))
                    reasons = [{
                        "code": code,
                        "path": "preparation.current_run",
                        "section": "preparation",
                        "label": "Current generated application package",
                        "severity": "blocking",
                        "blocking": True,
                        "message": message,
                        "action": action,
                    }]
                raise WorkflowTransitionError(
                    "a current complete generated application package is required before REVIEW",
                    api_detail={
                        "code": "prepare_review_readiness_blocked",
                        "message": "Case is not ready for review.",
                        "blocking_reasons": reasons,
                    },
                )

        if current == models.WorkflowState.REVIEW and target_state == models.WorkflowState.READY:
            if require_actor and not actor:
                raise WorkflowTransitionError("actor is required for explicit review approval")

    def can_transition(
        self, case_id: uuid.UUID, target_state: models.WorkflowState
    ) -> bool:
        case = self._case(case_id)
        try:
            self._validate_transition(case, target_state, require_actor=False)
        except WorkflowTransitionError:
            return False
        return True

    def transition(
        self,
        case_id: uuid.UUID,
        target_state: models.WorkflowState,
        actor: str | None = None,
        reason: str | None = None,
        audit_actor: User | None = None,
    ) -> tuple[models.WorkflowState, models.Case, models.WorkflowTransition]:
        case = self._case(case_id, for_update=True)
        self._validate_transition(case, target_state, actor=actor)
        previous_state = case.workflow_state
        case.workflow_state = target_state
        transition = models.WorkflowTransition(
            case_id=case.id,
            from_state=previous_state,
            to_state=target_state,
            actor=actor,
            reason=reason,
        )
        self.session.add(transition)
        record_audit(
            self.session,
            actor=audit_actor,
            action="WORKFLOW_TRANSITION",
            target_entity_type="CASE",
            target_entity_id=case.id,
            case_id=case.id,
            metadata={"from_state": previous_state.value, "to_state": target_state.value},
        )
        if target_state == models.WorkflowState.READY:
            record_audit(
                self.session, actor=audit_actor, action="FINAL_REVIEW_APPROVED",
                target_entity_type="CASE", target_entity_id=case.id, case_id=case.id,
            )
        elif target_state == models.WorkflowState.SUBMITTED:
            record_audit(
                self.session, actor=audit_actor, action="CASE_SUBMITTED",
                target_entity_type="CASE", target_entity_id=case.id, case_id=case.id,
            )
        self.session.commit()
        self.session.refresh(case)
        self.session.refresh(transition)
        return previous_state, case, transition

    def get_next_action(self, case_id: uuid.UUID) -> NextAction:
        case = self._case(case_id)

        conflicts = self._conflicts(case_id)
        if conflicts:
            fact = conflicts[0]
            return NextAction(
                type="RESOLVE_CONFLICT",
                title=f"Resolve conflicting information for {fact.key}",
                case_id=case_id,
                fact_id=fact.id,
                fact_key=fact.key,
            )

        import_conflict = self.session.execute(
            select(cm.CanadaImportCandidate, cm.CanadaLegacyImportRun)
            .join(cm.CanadaLegacyImportRun, cm.CanadaLegacyImportRun.id == cm.CanadaImportCandidate.import_run_id)
            .where(
                cm.CanadaLegacyImportRun.case_id == case_id,
                cm.CanadaImportCandidate.status.in_(("conflict", "ambiguous")),
            )
            .order_by(cm.CanadaImportCandidate.created_at, cm.CanadaImportCandidate.id)
            .limit(1)
        ).first()
        if import_conflict is not None:
            change, run = import_conflict
            return NextAction(
                type="REVIEW_CANADA_IMPORT",
                title=f"Review Canada import conflict: {change.employee_label}",
                case_id=case_id,
                import_run_id=run.id,
            )

        candidate = self.session.scalar(
            select(models.FactExtractionCandidate)
            .where(
                models.FactExtractionCandidate.case_id == case_id,
                models.FactExtractionCandidate.status.in_((
                    models.FactCandidateStatus.CONFLICT,
                    models.FactCandidateStatus.PROPOSED,
                )),
            )
            .order_by(
                models.FactExtractionCandidate.status.asc(),
                models.FactExtractionCandidate.created_at,
                models.FactExtractionCandidate.id,
            )
            .limit(1)
        )
        if candidate is not None:
            return NextAction(
                type="REVIEW_FACT_CANDIDATE",
                title=(
                    f"Resolve WhatsApp fact conflict: {candidate.key}"
                    if candidate.status == models.FactCandidateStatus.CONFLICT
                    else f"Review WhatsApp fact candidate: {candidate.key}"
                ),
                case_id=case_id,
                fact_key=candidate.key,
                fact_candidate_id=candidate.id,
            )

        if not case.visa_type.strip():
            return NextAction("CONFIRM_FACT", "Confirm the visa type", case_id, fact_key="visa_type")
        if not case.purpose.strip():
            return NextAction("CONFIRM_FACT", "Confirm the travel purpose", case_id, fact_key="purpose")
        for key, title in self.REQUIRED_FACTS.items():
            if self._confirmed_fact(case_id, key) is None:
                return NextAction("CONFIRM_FACT", title, case_id, fact_key=key)

        unassigned_document = self.session.scalar(
            select(models.Document)
            .where(
                models.Document.case_id == case_id,
                (models.Document.person_id.is_(None) | models.Document.document_type.is_(None)),
            )
            .order_by(models.Document.created_at, models.Document.id)
            .limit(1)
        )
        if unassigned_document is not None:
            return NextAction(
                type="ASSIGN_DOCUMENT",
                title="Assign an owner and document type",
                case_id=case_id,
                document_id=unassigned_document.id,
            )

        quality_document = self.session.scalar(
            select(models.Document)
            .join(models.RequirementDocumentMatch)
            .join(models.Requirement)
            .where(
                models.Document.case_id == case_id,
                models.Requirement.active.is_(True),
                models.Document.quality_status.not_in((
                    models.DocumentQualityState.PASSED,
                    models.DocumentQualityState.MANUAL_ACCEPTED,
                )),
            )
            .order_by(models.Document.created_at, models.Document.id)
            .limit(1)
        )
        if quality_document is not None:
            title = (
                "Run document quality check"
                if quality_document.quality_status == models.DocumentQualityState.NOT_CHECKED
                else "Review document quality"
            )
            return NextAction(
                type="REVIEW_DOCUMENT_QUALITY",
                title=title,
                case_id=case_id,
                document_id=quality_document.id,
            )

        pending_requirements = self._pending_blocking_requirements(case_id)
        if pending_requirements:
            requirement = pending_requirements[0]
            return NextAction(
                type="RESOLVE_REQUIREMENT",
                title=f"Resolve blocking requirement: {requirement.document_type}",
                case_id=case_id,
                requirement_id=requirement.id,
            )

        blocking_tasks = self._open_blocking_tasks(case_id)
        if blocking_tasks:
            task = blocking_tasks[0]
            return NextAction(
                type="COMPLETE_TASK",
                title=task.title,
                case_id=case_id,
                task_id=task.id,
            )

        if case.workflow_state == models.WorkflowState.INTAKE:
            return NextAction(
                "ADVANCE_WORKFLOW",
                "Intake is complete; move the case to documents",
                case_id,
                target_state=models.WorkflowState.DOCUMENTS,
            )
        if case.workflow_state == models.WorkflowState.DOCUMENTS:
            return NextAction(
                "PREPARE_APPLICATION",
                "Application is ready for preparation",
                case_id,
                target_state=models.WorkflowState.PREPARE,
            )
        if case.workflow_state == models.WorkflowState.PREPARE:
            from .preparation_runs import CanadaPreparationService

            preparation = CanadaPreparationService(self.session, self.storage)
            status = preparation.status(case_id)
            readiness = status.readiness
            if not readiness.ready:
                issue = readiness.issues[0]
                review_codes = {
                    "review_required", "unresolved_import_conflict",
                    "unresolved_fact_conflict", "inconsistent_data",
                    "ambiguous_reference", "unsupported_value",
                }
                action_type = (
                    "REVIEW_PREPARATION_DATA"
                    if issue.code in review_codes
                    else "COMPLETE_PREPARATION_DATA"
                )
                return NextAction(
                    action_type,
                    f"{issue.action} ({issue.label})",
                    case_id,
                    preparation_issue_code=issue.code,
                    preparation_path=issue.path,
                )
            if status.package_status in {"not_generated", "failed"}:
                return NextAction(
                    "GENERATE_APPLICATION", "Generate application package", case_id
                )
            if status.package_status in {"stale", "integrity_error"}:
                return NextAction(
                    "REGENERATE_APPLICATION", "Regenerate application package", case_id
                )
            if status.package_status == "generating":
                return NextAction("WAIT_FOR_GENERATION", "Application package is generating", case_id)
            return NextAction(
                "ADVANCE_WORKFLOW",
                "Preparation is complete; move the case to review",
                case_id,
                target_state=models.WorkflowState.REVIEW,
            )
        if case.workflow_state == models.WorkflowState.REVIEW:
            return NextAction("REVIEW_APPLICATION", "Review and explicitly approve the application", case_id)
        if case.workflow_state == models.WorkflowState.READY:
            return NextAction(
                "SUBMIT_APPLICATION",
                "Application is ready to be submitted",
                case_id,
                target_state=models.WorkflowState.SUBMITTED,
            )
        return NextAction("NO_ACTION", "Case has been submitted", case_id)
