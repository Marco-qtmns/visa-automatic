from __future__ import annotations

import uuid
from enum import StrEnum
from collections.abc import Generator
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_authenticated_request
from .database import get_session
from .models.auth import User, UserRole
from .models.core import ConversationImport, Document, Fact, FactExtractionCandidate, Requirement, Task
from .services.audit import queue_audit


class Permission(StrEnum):
    CASE_READ = "CASE_READ"
    CASE_CREATE = "CASE_CREATE"
    CASE_EDIT = "CASE_EDIT"
    FACT_READ = "FACT_READ"
    FACT_EDIT = "FACT_EDIT"
    DOCUMENT_READ = "DOCUMENT_READ"
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    DOCUMENT_EDIT = "DOCUMENT_EDIT"
    REQUIREMENT_EDIT = "REQUIREMENT_EDIT"
    TASK_EDIT = "TASK_EDIT"
    PREPARATION_READ = "PREPARATION_READ"
    PREPARATION_RUN = "PREPARATION_RUN"
    WORKFLOW_WORK = "WORKFLOW_WORK"
    WORKFLOW_REVIEW = "WORKFLOW_REVIEW"
    WORKFLOW_SUBMIT = "WORKFLOW_SUBMIT"
    CASE_AUDIT_READ = "CASE_AUDIT_READ"
    INTAKE_READ = "INTAKE_READ"
    INTAKE_PROCESS = "INTAKE_PROCESS"
    AUDIT_READ = "AUDIT_READ"
    USER_READ = "USER_READ"
    USER_CREATE = "USER_CREATE"
    USER_EDIT = "USER_EDIT"
    USER_DEACTIVATE = "USER_DEACTIVATE"
    USER_ROLE_CHANGE = "USER_ROLE_CHANGE"
    USER_MFA_RESET = "USER_MFA_RESET"
    USER_SESSION_REVOKE = "USER_SESSION_REVOKE"


class RouteAuthorizationClass(StrEnum):
    PUBLIC = "PUBLIC"
    AUTHENTICATED = "AUTHENTICATED"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    ADMIN_ONLY = "ADMIN_ONLY"


WORK_PERMISSIONS = frozenset({
    Permission.CASE_READ, Permission.CASE_CREATE, Permission.CASE_EDIT,
    Permission.FACT_READ, Permission.FACT_EDIT,
    Permission.DOCUMENT_READ, Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_EDIT,
    Permission.REQUIREMENT_EDIT, Permission.TASK_EDIT,
    Permission.PREPARATION_READ, Permission.PREPARATION_RUN,
    Permission.WORKFLOW_WORK,
})

INTAKE_PERMISSIONS = frozenset({Permission.INTAKE_READ, Permission.INTAKE_PROCESS})

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.CASE_WORKER: WORK_PERMISSIONS | INTAKE_PERMISSIONS,
    UserRole.REVIEWER: WORK_PERMISSIONS | frozenset({
        Permission.WORKFLOW_REVIEW,
        Permission.WORKFLOW_SUBMIT,
        Permission.CASE_AUDIT_READ,
    }),
    UserRole.ADMIN: frozenset(Permission),
}

WORKFLOW_TRANSITION_PERMISSIONS: dict[tuple[str, str], Permission] = {
    ("INTAKE", "DOCUMENTS"): Permission.WORKFLOW_WORK,
    ("DOCUMENTS", "INTAKE"): Permission.WORKFLOW_WORK,
    ("DOCUMENTS", "PREPARE"): Permission.WORKFLOW_WORK,
    ("PREPARE", "DOCUMENTS"): Permission.WORKFLOW_WORK,
    ("PREPARE", "REVIEW"): Permission.WORKFLOW_WORK,
    ("REVIEW", "DOCUMENTS"): Permission.WORKFLOW_REVIEW,
    ("REVIEW", "PREPARE"): Permission.WORKFLOW_WORK,
    ("REVIEW", "READY"): Permission.WORKFLOW_REVIEW,
    ("READY", "DOCUMENTS"): Permission.WORKFLOW_REVIEW,
    ("READY", "PREPARE"): Permission.WORKFLOW_REVIEW,
    ("READY", "REVIEW"): Permission.WORKFLOW_REVIEW,
    ("READY", "SUBMITTED"): Permission.WORKFLOW_SUBMIT,
}


def permissions_for_role(role: str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[UserRole(role)]
    except (ValueError, KeyError):
        return frozenset()


def user_has_permission(user: User, permission: Permission) -> bool:
    return user.is_active and permission in permissions_for_role(user.role)


def enforce_permission(user: User, permission: Permission) -> None:
    if not user_has_permission(user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission.")


def require_permission(permission: Permission) -> Callable:
    def dependency(user: User = Depends(require_authenticated_request)) -> User:
        enforce_permission(user, permission)
        return user

    dependency.permission = permission  # type: ignore[attr-defined]
    dependency.__name__ = f"require_{permission.value.casefold()}"
    return dependency


CurrentUser = Annotated[User, Depends(require_authenticated_request)]


ENDPOINT_PERMISSIONS: dict[str, Permission] = {}


def _assign(permission: Permission, *endpoint_names: str) -> None:
    for name in endpoint_names:
        if name in ENDPOINT_PERMISSIONS:
            raise RuntimeError(f"duplicate authorization classification for {name}")
        ENDPOINT_PERMISSIONS[name] = permission


_assign(Permission.CASE_READ,
    "application_bootstrap", "list_cases", "get_case", "list_persons", "get_person", "list_conversations",
    "list_conversation_messages", "get_workflow", "get_next_action", "get_application",
    "get_bundle", "mapping_specification", "list_imports", "get_import", "list_changes",
)
_assign(Permission.CASE_CREATE, "create_case", "preview_import", "create_import")
_assign(Permission.CASE_EDIT,
    "update_case", "create_person", "update_person", "paste_whatsapp_conversation",
    "upload_whatsapp_conversation", "extract_conversation_facts", "create_application",
    "update_application", "select_applicant", "assign_role", "upsert_biography",
    "create_citizenship", "create_identifier", "create_contact", "create_address",
    "update_address", "create_residence", "create_travel_document", "upsert_trip_plan",
    "create_organization", "create_funding_source", "create_host",
    "create_family_relationship", "create_education", "create_activity",
    "create_residence_history", "create_travel_history", "reorder_collection",
    "delete_collection_record", "upsert_official_answer", "upsert_official_explanation",
    "create_representative_profile", "revise_representative_profile",
    "authorize_representative", "add_provenance", "apply_import", "accept_change",
    "reject_change", "resolve_change",
)
_assign(Permission.FACT_READ,
    "list_facts", "get_fact", "list_fact_extraction_runs", "list_fact_candidates",
)
_assign(Permission.FACT_EDIT,
    "create_fact", "update_fact", "accept_fact_candidate", "correct_fact_candidate",
    "reject_fact_candidate",
)
_assign(Permission.DOCUMENT_READ,
    "list_documents", "list_document_types", "list_case_document_matches",
    "matching_requirements", "list_matched_requirements", "list_matched_documents",
    "get_document_content", "list_document_classifications", "get_document",
    "list_document_quality_checks", "list_requirement_completeness",
    "list_requirement_fulfillment_events",
)
_assign(Permission.DOCUMENT_UPLOAD, "create_document", "upload_document")
_assign(Permission.DOCUMENT_EDIT,
    "match_document", "unmatch_document", "classify_document",
    "accept_document_classification", "correct_document_classification",
    "reject_document_classification", "run_document_quality_check",
    "accept_document_quality", "reject_document_quality",
    "evaluate_requirement_completeness", "update_document",
)
_assign(Permission.REQUIREMENT_EDIT,
    "create_requirement", "list_requirements", "evaluate_requirements", "get_requirement",
    "update_requirement",
)
_assign(Permission.TASK_EDIT, "create_task", "list_tasks", "get_task", "update_task")
_assign(Permission.PREPARATION_READ,
    "preparation_policy", "adapter_mapping", "preparation_readiness",
    "evaluate_preparation_readiness", "preparation_status", "preparation_runs",
    "preparation_run", "preparation_artifacts", "preparation_artifact_content",
)
_assign(Permission.PREPARATION_RUN, "prepare_case")
_assign(Permission.WORKFLOW_WORK, "transition_case")
_assign(Permission.CASE_AUDIT_READ, "list_case_audit_events")
_assign(Permission.INTAKE_READ,
    "list_intake_submissions", "get_intake_submission", "intake_metrics",
)
_assign(Permission.INTAKE_PROCESS,
    "receive_google_forms_csv", "retry_intake_submission",
)

PUBLIC_ENDPOINTS = frozenset({"health", "health_live", "health_ready", "login", "verify_mfa"})
AUTHENTICATED_ENDPOINTS = frozenset({"me", "logout"})
ADMIN_ENDPOINT_PERMISSIONS = {
    "list_users": Permission.USER_READ,
    "add_user": Permission.USER_CREATE,
    "update_user": Permission.USER_EDIT,
    "revoke_user_sessions": Permission.USER_SESSION_REVOKE,
    "reset_user_mfa": Permission.USER_MFA_RESET,
    "list_security_audit_events": Permission.AUDIT_READ,
}


def route_authorization_class(endpoint_name: str) -> RouteAuthorizationClass | None:
    if endpoint_name in PUBLIC_ENDPOINTS:
        return RouteAuthorizationClass.PUBLIC
    if endpoint_name in AUTHENTICATED_ENDPOINTS:
        return RouteAuthorizationClass.AUTHENTICATED
    if endpoint_name in ADMIN_ENDPOINT_PERMISSIONS:
        return RouteAuthorizationClass.ADMIN_ONLY
    if endpoint_name in ENDPOINT_PERMISSIONS:
        return RouteAuthorizationClass.PERMISSION_REQUIRED
    return None


AUDIT_ACTIONS = {
    "create_fact": "FACT_CREATED",
    "update_fact": "FACT_CHANGED",
    "accept_fact_candidate": "FACT_CANDIDATE_ACCEPTED",
    "correct_fact_candidate": "FACT_CANDIDATE_CORRECTED",
    "reject_fact_candidate": "FACT_CANDIDATE_REJECTED",
    "create_document": "DOCUMENT_CREATED",
    "upload_document": "DOCUMENT_UPLOADED",
    "classify_document": "DOCUMENT_CLASSIFIED",
    "accept_document_classification": "DOCUMENT_CLASSIFICATION_ACCEPTED",
    "correct_document_classification": "DOCUMENT_CLASSIFICATION_CORRECTED",
    "reject_document_classification": "DOCUMENT_CLASSIFICATION_REJECTED",
    "run_document_quality_check": "DOCUMENT_QUALITY_CHECKED",
    "accept_document_quality": "DOCUMENT_QUALITY_ACCEPTED",
    "reject_document_quality": "DOCUMENT_QUALITY_REJECTED",
    "prepare_case": "PREPARATION_GENERATED",
    "create_import": "CASE_IMPORT_CREATED",
    "apply_import": "CASE_IMPORT_APPLIED",
}

CASE_ENTITY_PATHS = {
    "fact_id": Fact,
    "document_id": Document,
    "requirement_id": Requirement,
    "task_id": Task,
    "conversation_id": ConversationImport,
    "candidate_id": FactExtractionCandidate,
}


def _audit_case_id(session: Session, request: Request):
    if value := request.path_params.get("case_id"):
        return value
    for key, model in CASE_ENTITY_PATHS.items():
        if value := request.path_params.get(key):
            return session.scalar(select(model.case_id).where(model.id == uuid.UUID(str(value))))
    return None


def authorize_business_request(
    request: Request,
    user: User = Depends(require_authenticated_request),
    session: Session = Depends(get_session),
) -> Generator[User, None, None]:
    endpoint = request.scope.get("endpoint")
    endpoint_name = getattr(endpoint, "__name__", "")
    permission = ENDPOINT_PERMISSIONS.get(endpoint_name)
    if permission is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Route authorization classification is missing.",
        )
    enforce_permission(user, permission)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and endpoint_name not in {
        "create_case", "transition_case", "prepare_case",
        "receive_google_forms_csv", "retry_intake_submission",
    }:
        target_id = next(
            (str(value) for key, value in request.path_params.items() if key.endswith("_id")),
            None,
        )
        queue_audit(
            session,
            actor=user,
            action=AUDIT_ACTIONS.get(endpoint_name, endpoint_name.upper()),
            target_entity_type=endpoint_name.split("_", 1)[-1].upper(),
            target_entity_id=target_id,
            case_id=_audit_case_id(session, request),
            request_id=request.headers.get("x-request-id", "")[:64] or None,
        )
    yield user


def enforce_workflow_target(
    user: User, target_state: str, *, current_state: str | None = None
) -> None:
    permission = WORKFLOW_TRANSITION_PERMISSIONS.get((current_state or "", target_state))
    if permission is None:
        # Invalid domain transitions are still decided by WorkflowService (409),
        # while attempts to cross a final-review boundary remain role-protected.
        if target_state == "SUBMITTED":
            permission = Permission.WORKFLOW_SUBMIT
        elif target_state == "READY" or current_state in {"REVIEW", "READY"}:
            permission = Permission.WORKFLOW_REVIEW
        else:
            permission = Permission.WORKFLOW_WORK
    enforce_permission(user, permission)
