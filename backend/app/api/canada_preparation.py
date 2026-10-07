from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from ..authorization import CurrentUser
from ..config.canada_form_adapter_mapping import (
    ADAPTER_MAPPING_SPEC_JSON,
    ADAPTER_MAPPING_VERSION,
)
from ..config.canada_preparation_policy import (
    POLICY_SPEC_JSON,
    POLICY_VERSION,
    PROJECTION_SPEC_JSON,
)
from ..database import get_session
from ..integrations.canada_forms import CanadaFormGeneratorAdapter, LegacyCanadaFormGeneratorAdapter
from ..schemas.canada_preparation import (
    PreparationArtifactRead,
    PreparationReadinessResult,
    PreparationRequest,
    PreparationRunDetail,
    PreparationStatusResult,
)
from ..services.canada_preparation import CanadaPreparationReadinessService
from ..services.preparation_runs import CanadaPreparationService
from .core import GeneratedStorageDep


router = APIRouter(tags=["Canada preparation"])
SessionDep = Annotated[Session, Depends(get_session)]


def canada_form_generator_provider() -> CanadaFormGeneratorAdapter:
    return LegacyCanadaFormGeneratorAdapter()


GeneratorDep = Annotated[CanadaFormGeneratorAdapter, Depends(canada_form_generator_provider)]


@router.get("/canada-preparation-policy")
def preparation_policy():
    """Expose the versioned policy and audited projection for inspection."""
    return {
        "policy_version": POLICY_VERSION,
        "rule_count": len(POLICY_SPEC_JSON),
        "rules": list(POLICY_SPEC_JSON),
        "projection_count": len(PROJECTION_SPEC_JSON),
        "projections": list(PROJECTION_SPEC_JSON),
    }


@router.get("/canada-form-adapter-mapping")
def adapter_mapping():
    return {
        "adapter_mapping_version": ADAPTER_MAPPING_VERSION,
        "mapping_count": len(ADAPTER_MAPPING_SPEC_JSON),
        "mappings": list(ADAPTER_MAPPING_SPEC_JSON),
    }


@router.get(
    "/cases/{case_id}/preparation-readiness",
    response_model=PreparationReadinessResult,
)
def preparation_readiness(case_id: uuid.UUID, session: SessionDep):
    return CanadaPreparationReadinessService(session).evaluate(case_id)


@router.post(
    "/cases/{case_id}/preparation-readiness/evaluate",
    response_model=PreparationReadinessResult,
)
def evaluate_preparation_readiness(case_id: uuid.UUID, session: SessionDep):
    # Evaluation is intentionally read-only and is not persisted as a run.
    return CanadaPreparationReadinessService(session).evaluate(case_id)


@router.get("/cases/{case_id}/preparation", response_model=PreparationStatusResult)
def preparation_status(case_id: uuid.UUID, session: SessionDep, storage: GeneratedStorageDep):
    return CanadaPreparationService(session, storage).status(case_id)


@router.post("/cases/{case_id}/prepare", response_model=PreparationRunDetail)
def prepare_case(
    case_id: uuid.UUID,
    payload: PreparationRequest,
    session: SessionDep,
    storage: GeneratedStorageDep,
    generator: GeneratorDep,
    user: CurrentUser,
):
    service = CanadaPreparationService(session, storage, generator)
    run = service.prepare(case_id, initiated_by=payload.initiated_by, audit_actor=user)
    return service.detail(run)


@router.get("/cases/{case_id}/preparation-runs", response_model=list[PreparationRunDetail])
def preparation_runs(case_id: uuid.UUID, session: SessionDep, storage: GeneratedStorageDep):
    service = CanadaPreparationService(session, storage)
    return [service.detail(run) for run in service.list_runs(case_id)]


@router.get("/preparation-runs/{run_id}", response_model=PreparationRunDetail)
def preparation_run(run_id: uuid.UUID, session: SessionDep, storage: GeneratedStorageDep):
    service = CanadaPreparationService(session, storage)
    return service.detail(service.get_run(run_id))


@router.get(
    "/preparation-runs/{run_id}/artifacts",
    response_model=list[PreparationArtifactRead],
)
def preparation_artifacts(run_id: uuid.UUID, session: SessionDep, storage: GeneratedStorageDep):
    return CanadaPreparationService(session, storage).artifacts(run_id)


@router.get("/preparation-artifacts/{artifact_id}/content")
def preparation_artifact_content(
    artifact_id: uuid.UUID,
    session: SessionDep,
    storage: GeneratedStorageDep,
    download: bool = False,
):
    artifact = CanadaPreparationService(session, storage).get_artifact(artifact_id)
    source = storage.open(artifact.storage_key)
    disposition = "attachment" if download else "inline"
    filename = quote(artifact.display_filename, safe="")
    return StreamingResponse(
        source,
        media_type=artifact.mime_type,
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}"},
        background=BackgroundTask(source.close),
    )
