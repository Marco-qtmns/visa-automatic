from __future__ import annotations

import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..models import canada as cm
from ..schemas.operational import CaseSummaryRead


UNIDENTIFIED_APPLICANT = "Applicant not identified yet"


def classify_work_queue(workflow_state: models.WorkflowState, issue_count: int) -> str:
    """One case, one queue. Workflow gates take precedence over exceptions."""
    if workflow_state == models.WorkflowState.REVIEW:
        return "REVIEW"
    if workflow_state == models.WorkflowState.READY:
        return "READY"
    if issue_count:
        return "ACTION_REQUIRED"
    return "WAITING"


class OperationalCaseService:
    """Small work-queue projections; never loads full case aggregates."""

    def __init__(self, session: Session):
        self.session = session

    def case_summaries(self) -> tuple[list[CaseSummaryRead], float]:
        started = time.perf_counter()
        applicant_names = {
            case_id: f"{first_name} {last_name}".strip()
            for case_id, first_name, last_name, roles in self.session.execute(
                select(
                    models.Person.case_id, models.Person.first_name,
                    models.Person.last_name, models.Person.roles,
                )
            )
            if "applicant" in roles
        }
        pending_requirements = (
            select(
                models.Requirement.case_id.label("case_id"),
                func.count(models.Requirement.id).label("count"),
            )
            .where(
                models.Requirement.active.is_(True),
                models.Requirement.is_blocking.is_(True),
                models.Requirement.fulfillment_status
                == models.RequirementFulfillmentStatus.PENDING,
            )
            .group_by(models.Requirement.case_id)
            .subquery()
        )
        blocking_tasks = (
            select(
                models.Task.case_id.label("case_id"),
                func.count(models.Task.id).label("count"),
            )
            .where(
                models.Task.blocking.is_(True),
                models.Task.status.in_(("open", "in_progress")),
            )
            .group_by(models.Task.case_id)
            .subquery()
        )
        fact_conflicts = (
            select(
                models.Fact.case_id.label("case_id"),
                func.count(models.Fact.id).label("count"),
            )
            .where(models.Fact.status == "conflict")
            .group_by(models.Fact.case_id)
            .subquery()
        )
        import_issues = (
            select(
                cm.CanadaLegacyImportRun.case_id.label("case_id"),
                func.count(cm.CanadaImportCandidate.id).label("count"),
            )
            .join(
                cm.CanadaImportCandidate,
                cm.CanadaImportCandidate.import_run_id == cm.CanadaLegacyImportRun.id,
            )
            .where(cm.CanadaImportCandidate.status.in_(("conflict", "ambiguous")))
            .group_by(cm.CanadaLegacyImportRun.case_id)
            .subquery()
        )
        rows = self.session.execute(
            select(
                models.Case,
                func.coalesce(pending_requirements.c.count, 0),
                func.coalesce(blocking_tasks.c.count, 0),
                func.coalesce(fact_conflicts.c.count, 0),
                func.coalesce(import_issues.c.count, 0),
            )
            .outerjoin(pending_requirements, pending_requirements.c.case_id == models.Case.id)
            .outerjoin(blocking_tasks, blocking_tasks.c.case_id == models.Case.id)
            .outerjoin(fact_conflicts, fact_conflicts.c.case_id == models.Case.id)
            .outerjoin(import_issues, import_issues.c.case_id == models.Case.id)
            .order_by(models.Case.updated_at.desc(), models.Case.id)
        ).all()
        summaries: list[CaseSummaryRead] = []
        for record, requirement_count, task_count, conflict_count, import_count in rows:
            issue_count = int(requirement_count + task_count + conflict_count + import_count)
            if conflict_count or import_count:
                next_action = "Resolve conflicting application information"
            elif requirement_count:
                next_action = "Provide the next missing document"
            elif task_count:
                next_action = "Complete the next blocking task"
            else:
                next_action = {
                    models.WorkflowState.INTAKE: "Continue application",
                    models.WorkflowState.DOCUMENTS: "Continue document intake",
                    models.WorkflowState.PREPARE: "Generate or update preparation package",
                    models.WorkflowState.REVIEW: "Review application",
                    models.WorkflowState.READY: "Mark submitted",
                    models.WorkflowState.SUBMITTED: "No action required",
                }[record.workflow_state]
            queue = classify_work_queue(record.workflow_state, issue_count)
            summaries.append(CaseSummaryRead(
                id=record.id,
                case_number=record.case_number,
                display_name=applicant_names.get(record.id, UNIDENTIFIED_APPLICANT),
                visa_type=record.visa_type,
                purpose=record.purpose,
                workflow_state=record.workflow_state,
                issue_count=issue_count,
                next_action=next_action,
                queue=queue,
                updated_at=record.updated_at,
            ))
        return summaries, (time.perf_counter() - started) * 1000
