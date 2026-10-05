from __future__ import annotations

import argparse
import hashlib
import json
import uuid

from sqlalchemy import func, select

from backend.app import models
from backend.app.database import SessionLocal
from backend.app.models import canada as cm
from backend.app.services.preparation_runs import CanadaPreparationService
from backend.app.storage import LocalStorageProvider


def verify(case_id: uuid.UUID, run_id: uuid.UUID, document_id: uuid.UUID) -> dict[str, object]:
    case_id = uuid.UUID(str(case_id))
    run_id = uuid.UUID(str(run_id))
    document_id = uuid.UUID(str(document_id))
    document_storage = LocalStorageProvider.from_environment()
    generated_storage = LocalStorageProvider.generated_from_environment()
    with SessionLocal() as session:
        case = session.get(models.Case, case_id)
        if case is None or case.workflow_state != models.WorkflowState.PREPARE:
            raise RuntimeError("synthetic case or workflow state missing")
        application_count = session.scalar(
            select(func.count()).select_from(cm.CanadaApplication).where(
                cm.CanadaApplication.case_id == case_id
            )
        )
        requirement_count = session.scalar(
            select(func.count()).select_from(models.Requirement).where(
                models.Requirement.case_id == case_id
            )
        )
        document = session.get(models.Document, document_id)
        if not application_count or not requirement_count or document is None:
            raise RuntimeError("synthetic canonical state missing")
        if document.case_id != case_id or not document_storage.exists(document.storage_path):
            raise RuntimeError("synthetic document missing")

        service = CanadaPreparationService(session, generated_storage)
        run = service.get_run(run_id)
        if run.case_id != case_id or run.status != "succeeded":
            raise RuntimeError("synthetic preparation run missing")
        artifacts = service.artifacts(run_id)
        for artifact in artifacts:
            if not generated_storage.exists(artifact.storage_key):
                raise RuntimeError("synthetic artifact missing")
            with generated_storage.open(artifact.storage_key) as source:
                if hashlib.sha256(source.read()).hexdigest() != artifact.file_hash:
                    raise RuntimeError("synthetic artifact hash mismatch")
        _readiness, current_run, reason = service.current_package(case_id)
        if current_run is None or current_run.id != run_id or reason is not None:
            raise RuntimeError("synthetic package is not current")
        return {
            "case_id": str(case_id),
            "run_id": str(run_id),
            "workflow_state": case.workflow_state.value,
            "package_status": "current",
            "canonical_application_count": application_count,
            "requirement_count": requirement_count,
            "document_count": 1,
            "artifact_types": sorted(item.artifact_type for item in artifacts),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a synthetic D1 case without exposing payloads.")
    parser.add_argument("--case-id", type=uuid.UUID, required=True)
    parser.add_argument("--run-id", type=uuid.UUID, required=True)
    parser.add_argument("--document-id", type=uuid.UUID, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.case_id, args.run_id, args.document_id), sort_keys=True))


if __name__ == "__main__":
    main()
