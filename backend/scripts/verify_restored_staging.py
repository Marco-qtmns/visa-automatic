from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select, text

from backend.app import models
from backend.app.database import SessionLocal
from backend.app.deployment_preflight import EXPECTED_ALEMBIC_HEAD
from backend.app.models import canada as cm
from backend.app.services.preparation_runs import CanadaPreparationService
from backend.app.storage import LocalStorageProvider


def verify() -> dict[str, object]:
    document_storage = LocalStorageProvider.from_environment()
    generated_storage = LocalStorageProvider.generated_from_environment()
    with SessionLocal() as session:
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_ALEMBIC_HEAD:
            raise RuntimeError("restore_schema_revision_mismatch")
        counts = {
            "cases": session.scalar(select(func.count()).select_from(models.Case)),
            "canada_applications": session.scalar(
                select(func.count()).select_from(cm.CanadaApplication)
            ),
            "documents": session.scalar(select(func.count()).select_from(models.Document)),
            "preparation_runs": session.scalar(
                select(func.count()).select_from(models.PreparationRun).where(
                    models.PreparationRun.status == "succeeded"
                )
            ),
            "preparation_artifacts": session.scalar(
                select(func.count()).select_from(models.PreparationArtifact)
            ),
        }
        if any(not value for value in counts.values()):
            raise RuntimeError("restore_synthetic_state_missing")
        for document in session.scalars(select(models.Document)):
            if not document_storage.exists(document.storage_path):
                raise RuntimeError("restore_document_missing")
        artifact_types: set[str] = set()
        for artifact in session.scalars(select(models.PreparationArtifact)):
            artifact_types.add(artifact.artifact_type)
            if not generated_storage.exists(artifact.storage_key):
                raise RuntimeError("restore_artifact_missing")
            with generated_storage.open(artifact.storage_key) as source:
                if hashlib.sha256(source.read()).hexdigest() != artifact.file_hash:
                    raise RuntimeError("restore_artifact_hash_mismatch")
        current_packages = 0
        service = CanadaPreparationService(session, generated_storage)
        case_ids = list(session.scalars(
            select(models.PreparationRun.case_id).where(
                models.PreparationRun.status == "succeeded"
            ).distinct()
        ))
        for case_id in case_ids:
            _readiness, current, reason = service.current_package(case_id)
            if current is not None and reason is None:
                current_packages += 1
        if not current_packages:
            raise RuntimeError("restore_current_package_missing")
        return {
            "status": "PASS",
            "alembic_revision": revision,
            "counts": counts,
            "current_package_count": current_packages,
            "artifact_types": sorted(artifact_types),
        }


def main() -> None:
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
