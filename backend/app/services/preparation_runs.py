from __future__ import annotations

import hashlib
import os
import uuid
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..models.auth import User
from ..models.core import utcnow
from ..config.canada_preparation_policy import PAYLOAD_SCHEMA_VERSION, POLICY_VERSION
from ..integrations.canada_forms import (
    ADAPTER_VERSION,
    CONTINUATION_ARTIFACT_TYPE,
    GENERATOR_VERSION,
    MANDATORY_ARTIFACT_TYPES,
    CanadaFormGeneratorAdapter,
    continuation_required,
)
from ..schemas import canada_preparation as schemas
from ..storage import LocalStorageProvider, StorageProvider
from .canada_preparation import (
    CanadaPreparationReadinessService,
    CanonicalPreparationPayloadBuilder,
    canonical_payload_hash,
)
from .core import DomainNotFound, DomainValidationError
from .audit import record_audit


ARTIFACT_FILENAMES = {
    "imm5257": "IMM5257-DRAFT.pdf",
    "imm5707": "IMM5707-DRAFT.pdf",
    "imm5476": "IMM5476-DRAFT.pdf",
    "imm5257_continuation": "IMM5257-CONTINUATION-DRAFT.pdf",
}


class PreparationExecutionError(RuntimeError):
    def __init__(self, code: str, safe_summary: str):
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


def configured_max_generated_bytes() -> int:
    raw = os.environ.get("MAX_GENERATED_ARTIFACT_MB", "30")
    try:
        value = int(raw)
    except ValueError as error:
        raise DomainValidationError("MAX_GENERATED_ARTIFACT_MB must be a positive integer") from error
    if value <= 0:
        raise DomainValidationError("MAX_GENERATED_ARTIFACT_MB must be a positive integer")
    return value * 1024 * 1024


class CanadaPreparationService:
    """Orchestrates canonical generation, persistence, currency and integrity."""

    def __init__(
        self,
        session: Session,
        storage: StorageProvider | None = None,
        adapter: CanadaFormGeneratorAdapter | None = None,
    ):
        self.session = session
        self.storage = storage or LocalStorageProvider.generated_from_environment()
        self.adapter = adapter

    def prepare(
        self, case_id: uuid.UUID, *, initiated_by: str, audit_actor: User | None = None
    ) -> models.PreparationRun:
        case = self.session.get(models.Case, case_id)
        if case is None:
            raise DomainNotFound("Case not found")
        if case.workflow_state != models.WorkflowState.PREPARE:
            raise DomainValidationError("case must be in PREPARE before generation")
        if not initiated_by.strip():
            raise DomainValidationError("initiated_by is required")
        readiness = CanadaPreparationReadinessService(self.session).evaluate(case_id)
        if not readiness.ready:
            raise DomainValidationError("canonical Canada application is not preparation-ready")
        payload = CanonicalPreparationPayloadBuilder(self.session).build(case_id)
        payload_hash = canonical_payload_hash(payload)
        if self.adapter is None:
            raise DomainValidationError("Canada form generator adapter is not configured")

        run = models.PreparationRun(
            case_id=case_id, status="running", initiated_by=initiated_by.strip(),
            payload_schema_version=payload.schema_version,
            preparation_policy_version=payload.policy_version,
            payload_hash=payload_hash, adapter_version=self.adapter.adapter_version,
            generator_version=self.adapter.generator_version,
        )
        self.session.add(run)
        try:
            self.session.flush()
            record_audit(
                self.session, actor=audit_actor, action="PREPARATION_RUN_CREATED",
                target_entity_type="PREPARATION_RUN", target_entity_id=run.id,
                case_id=case_id,
            )
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DomainValidationError("a preparation run is already active for this case") from error
        self.session.refresh(run)

        stored_keys: list[str] = []
        try:
            generated = self.adapter.generate(payload)
            self._validate_manifest(generated, continuation_required(payload))
            max_bytes = configured_max_generated_bytes()
            for result in generated:
                stored = self.storage.save(BytesIO(result.content), max_bytes=max_bytes)
                stored_keys.append(stored.key)
                self.session.add(models.PreparationArtifact(
                    preparation_run_id=run.id, case_id=case_id,
                    artifact_type=result.artifact_type,
                    display_filename=result.filename, storage_key=stored.key,
                    mime_type=result.mime_type, generator=result.generator,
                    generator_version=result.generator_version,
                    template_identifier=result.template_identifier,
                    template_hash=result.template_hash,
                    file_hash=hashlib.sha256(result.content).hexdigest(),
                ))
            current = CanadaPreparationReadinessService(self.session).evaluate(case_id)
            if not current.ready:
                raise PreparationExecutionError("payload_changed", "Application data changed during generation.")
            rebuilt = CanonicalPreparationPayloadBuilder(self.session).build(case_id)
            if canonical_payload_hash(rebuilt) != payload_hash:
                raise PreparationExecutionError("payload_changed", "Application data changed during generation.")
            run.status = "succeeded"
            run.completed_at = utcnow()
            self.session.flush()
            record_audit(
                self.session, actor=audit_actor, action="PREPARATION_GENERATION_COMPLETED",
                target_entity_type="PREPARATION_RUN", target_entity_id=run.id,
                case_id=case_id,
            )
            for artifact in run.artifacts:
                record_audit(
                    self.session, actor=audit_actor,
                    action="PREPARATION_ARTIFACT_GENERATED",
                    target_entity_type="PREPARATION_ARTIFACT", target_entity_id=artifact.id,
                    case_id=case_id, metadata={"artifact_type": artifact.artifact_type},
                )
            self.session.commit()
            self.session.refresh(run)
            return run
        except PreparationExecutionError as error:
            self.session.rollback()
            self._cleanup(stored_keys)
            self._fail(run.id, error.code, error.safe_summary, audit_actor=audit_actor)
            raise DomainValidationError(error.safe_summary) from error
        except Exception as error:
            self.session.rollback()
            self._cleanup(stored_keys)
            self._fail(
                run.id, "generator_failed", "Application package generation failed.",
                audit_actor=audit_actor,
            )
            raise DomainValidationError("Application package generation failed.") from error

    def _validate_manifest(self, generated, needs_continuation: bool) -> None:
        types = [item.artifact_type for item in generated]
        if len(types) != len(set(types)):
            raise PreparationExecutionError("artifact_manifest_invalid", "Generator returned duplicate artifact types.")
        expected = set(MANDATORY_ARTIFACT_TYPES)
        if needs_continuation: expected.add(CONTINUATION_ARTIFACT_TYPE)
        if set(types) != expected:
            raise PreparationExecutionError("artifact_manifest_invalid", "Generator did not return the complete expected form package.")
        for item in generated:
            if item.artifact_type not in ARTIFACT_FILENAMES:
                raise PreparationExecutionError("artifact_manifest_invalid", "Generator returned an unknown artifact type.")
            if item.filename != ARTIFACT_FILENAMES[item.artifact_type]:
                raise PreparationExecutionError("artifact_manifest_invalid", "Generator returned an unexpected artifact filename.")
            if item.mime_type != "application/pdf" or not item.content.startswith(b"%PDF-"):
                raise PreparationExecutionError("artifact_manifest_invalid", "Generator returned an invalid PDF artifact.")
            if not item.template_hash or len(item.template_hash) != 64:
                raise PreparationExecutionError("artifact_manifest_invalid", "Generator template provenance is incomplete.")

    def _fail(
        self, run_id: uuid.UUID, code: str, summary: str, *, audit_actor: User | None = None
    ) -> None:
        run = self.session.get(models.PreparationRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.error_code = code
        run.error_summary = summary[:255]
        run.completed_at = utcnow()
        record_audit(
            self.session, actor=audit_actor, action="PREPARATION_GENERATION_FAILED",
            target_entity_type="PREPARATION_RUN", target_entity_id=run.id,
            case_id=run.case_id, outcome="FAILURE", metadata={"error_code": code},
        )
        self.session.commit()

    def list_runs(self, case_id: uuid.UUID) -> list[models.PreparationRun]:
        if self.session.get(models.Case, case_id) is None: raise DomainNotFound("Case not found")
        return list(self.session.scalars(select(models.PreparationRun).where(
            models.PreparationRun.case_id == case_id
        ).order_by(models.PreparationRun.created_at.desc(), models.PreparationRun.id.desc())))

    def get_run(self, run_id: uuid.UUID) -> models.PreparationRun:
        run = self.session.get(models.PreparationRun, run_id)
        if run is None: raise DomainNotFound("Preparation run not found")
        return run

    def artifacts(self, run_id: uuid.UUID) -> list[models.PreparationArtifact]:
        self.get_run(run_id)
        return list(self.session.scalars(select(models.PreparationArtifact).where(
            models.PreparationArtifact.preparation_run_id == run_id
        ).order_by(models.PreparationArtifact.created_at, models.PreparationArtifact.id)))

    def get_artifact(self, artifact_id: uuid.UUID) -> models.PreparationArtifact:
        artifact = self.session.get(models.PreparationArtifact, artifact_id)
        if artifact is None: raise DomainNotFound("Preparation artifact not found")
        return artifact

    def current_package(self, case_id: uuid.UUID):
        readiness = CanadaPreparationReadinessService(self.session).evaluate(case_id)
        if not readiness.ready: return readiness, None, "readiness_blocked"
        payload = CanonicalPreparationPayloadBuilder(self.session).build(case_id)
        payload_hash = canonical_payload_hash(payload)
        runs = list(self.session.scalars(select(models.PreparationRun).where(
            models.PreparationRun.case_id == case_id,
            models.PreparationRun.status == "succeeded",
            models.PreparationRun.payload_hash == payload_hash,
            models.PreparationRun.payload_schema_version == PAYLOAD_SCHEMA_VERSION,
            models.PreparationRun.preparation_policy_version == POLICY_VERSION,
            models.PreparationRun.adapter_version == ADAPTER_VERSION,
            models.PreparationRun.generator_version == GENERATOR_VERSION,
        ).order_by(models.PreparationRun.created_at.desc(), models.PreparationRun.id.desc())))
        if not runs: return readiness, None, "no_matching_success"
        run = runs[0]
        expected = set(MANDATORY_ARTIFACT_TYPES)
        if continuation_required(payload): expected.add(CONTINUATION_ARTIFACT_TYPE)
        artifacts = self.artifacts(run.id)
        if {item.artifact_type for item in artifacts} != expected:
            return readiness, None, "artifact_manifest_missing"
        for artifact in artifacts:
            if not self.storage.exists(artifact.storage_key):
                return readiness, None, "artifact_missing"
            try:
                with self.storage.open(artifact.storage_key) as source:
                    digest = hashlib.sha256(source.read()).hexdigest()
            except Exception:
                return readiness, None, "artifact_missing"
            if digest != artifact.file_hash:
                return readiness, None, "artifact_hash_mismatch"
        return readiness, run, None

    def _cleanup(self, storage_keys: list[str]) -> None:
        for key in storage_keys:
            try:
                self.storage.delete(key)
            except Exception:
                # Cleanup must never prevent the durable failed-run state.
                pass

    def status(self, case_id: uuid.UUID) -> schemas.PreparationStatusResult:
        case = self.session.get(models.Case, case_id)
        if case is None: raise DomainNotFound("Case not found")
        readiness, current, integrity = self.current_package(case_id)
        runs = self.list_runs(case_id)
        latest = runs[0] if runs else None
        payload_hash = readiness.payload_hash
        if not readiness.ready:
            package_status = "blocked"
        elif current:
            package_status = "current"
        elif latest and latest.status == "running":
            package_status = "generating"
        elif integrity and integrity.startswith("artifact_"):
            package_status = "integrity_error"
        elif latest and latest.status == "failed":
            package_status = "failed"
        elif any(run.status == "succeeded" for run in runs):
            package_status = "stale"
        else:
            package_status = "not_generated"
        discrepancy = package_status not in {"current", "not_generated", "generating"}
        if case.workflow_state == models.WorkflowState.SUBMITTED and discrepancy:
            package_status = "submitted_discrepancy"
        elif case.workflow_state in {models.WorkflowState.REVIEW, models.WorkflowState.READY} and package_status != "current":
            self._regress_stale_case(case_id, readiness)
        return schemas.PreparationStatusResult(
            readiness=readiness, latest_run=self.detail(latest),
            current_run=self.detail(current), payload_hash=payload_hash,
            package_status=package_status,
            integrity_error=integrity if package_status in {"integrity_error", "submitted_discrepancy"} else None,
        )

    def _regress_stale_case(self, case_id, readiness) -> None:
        pending_documents = any(item.code == "blocking_requirement" for item in readiness.issues)
        target = models.WorkflowState.DOCUMENTS if pending_documents else models.WorkflowState.PREPARE
        from .workflow import WorkflowService
        WorkflowService(self.session, self.storage).transition(
            case_id, target, actor="system:preparation-stale",
            reason="Current generated application package became stale or invalid.",
        )

    def detail(self, run):
        if run is None: return None
        data = schemas.PreparationRunRead.model_validate(run).model_dump()
        return schemas.PreparationRunDetail(**data, artifacts=tuple(
            schemas.PreparationArtifactRead.model_validate(item) for item in self.artifacts(run.id)
        ))
