from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from canada.models import Activity, CanadaCase
from canada.case_store import save_case
from backend.app import models
from backend.app.config.canada_import_mapping import AUDITED_GENERATOR_MAPPINGS
from backend.app.models import canada as cm
from backend.app.schemas.canada import CanadaApplicationCreate
from backend.app.services.canada import CanadaApplicationService
from backend.app.services.canada_imports import CanadaLegacyImportService
from backend.app.services.core import DomainValidationError
from backend.app.services.workflow import WorkflowService


def setup_application(session):
    case = models.Case(case_number=f"SYN-IMPORT-{uuid.uuid4().hex[:8]}", visa_type="canada_trv", purpose="Synthetic visit")
    session.add(case); session.flush()
    applicant = models.Person(case_id=case.id, first_name="Amina", last_name="Synthetic", roles=["applicant"])
    session.add(applicant); session.commit()
    app = CanadaApplicationService(session).create_application(case.id, CanadaApplicationCreate(applicant_person_id=applicant.id))
    return case, applicant, app


def preview(session, case, legacy, digest="a" * 64):
    return CanadaLegacyImportService(session).preview_case(
        case.id, legacy, source_type="canada_case_json",
        source_identifier="synthetic.canada-case.json", source_hash=digest,
        imported_by="tester@example.invalid",
    )


def test_mapping_has_all_138_explicit_unique_paths():
    assert len(AUDITED_GENERATOR_MAPPINGS) == 138
    assert len({entry.legacy_path for entry in AUDITED_GENERATOR_MAPPINGS}) == 138
    assert all(entry.canonical_target and entry.source_classification and entry.review_policy and entry.conflict_policy for entry in AUDITED_GENERATOR_MAPPINGS)


def test_preview_new_same_empty_and_idempotent(session):
    case, applicant, _app = setup_application(session)
    legacy = CanadaCase(); legacy.identity.family_name = applicant.last_name
    legacy.identity.given_names = "Changed"; legacy.contact.email = ""
    run = preview(session, case, legacy)
    changes = CanadaLegacyImportService(session).changes(run.id)
    assert {(item.source_path, item.status) for item in changes} == {
        ("identity.family_name", "same"), ("identity.given_names", "conflict")
    }
    assert preview(session, case, legacy).id == run.id
    assert session.scalar(select(func.count(cm.CanadaLegacyImportRun.id))) == 1


def test_confirmed_conflict_requires_resolution_and_safe_batch_excludes_it(session):
    case, applicant, _app = setup_application(session)
    session.add(cm.FieldProvenanceReview(
        case_id=case.id, entity_type="person", entity_id=applicant.id, field_key="last_name",
        source_type="manual", source_reference="employee", review_state="confirmed",
    )); session.commit()
    legacy = CanadaCase(); legacy.identity.family_name = "Different"; legacy.trip.purpose = "Visit friends"
    run = preview(session, case, legacy)
    importer = CanadaLegacyImportService(session)
    conflict = next(item for item in importer.changes(run.id) if item.source_path == "identity.family_name")
    assert conflict.status == "conflict" and conflict.conflict_type == "confirmed_canonical_value"
    with pytest.raises(DomainValidationError, match="resolve"):
        importer.review(conflict.id, "accept", "employee")
    importer.apply(run.id, mode="safe", reviewed_by="employee")
    assert session.get(models.Person, applicant.id).last_name == "Synthetic"
    plan = session.scalar(select(cm.TripPlan).where(cm.TripPlan.application_id == _app.id))
    assert plan.intake_purpose_text == "Visit friends" and plan.imm5257_purpose_code is None
    importer.review(conflict.id, "use_imported", "employee")
    importer.apply(run.id, reviewed_by="employee")
    assert session.get(models.Person, applicant.id).last_name == "Different"


def test_activity_source_link_reuses_identity_on_changed_reimport(session):
    case, _applicant, app = setup_application(session)
    first = CanadaCase(); first.activities = [Activity(source_role="csv", source_block_index=1, position="Analyst")]
    run1 = preview(session, case, first, "1" * 64)
    importer = CanadaLegacyImportService(session); importer.apply(run1.id, mode="safe")
    activity = session.scalar(select(cm.ActivityRecord).where(cm.ActivityRecord.application_id == app.id))
    assert activity.position == "Analyst"
    second = CanadaCase(); second.activities = [Activity(source_role="csv", source_block_index=1, position="Manager")]
    run2 = preview(session, case, second, "2" * 64)
    position = next(item for item in importer.changes(run2.id) if item.source_path == "activities[*].position")
    assert position.target_entity_id == activity.id and position.status == "conflict"
    importer.review(position.id, "use_imported"); importer.apply(run2.id)
    assert session.scalar(select(func.count(cm.ActivityRecord.id))) == 1
    assert session.get(cm.ActivityRecord, activity.id).position == "Manager"


def test_official_unknown_and_fact_contradiction_surface_review(session):
    case, applicant, _app = setup_application(session)
    session.add(models.Fact(case_id=case.id, person_id=applicant.id, key="host.exists", value_json=False, source_type="manual", source_reference="employee", status="confirmed")); session.commit()
    legacy = CanadaCase(); legacy.official_review.previous_residence_over_six_months = "unknown"
    legacy.trip.host_name = "Synthetic Host"
    run = preview(session, case, legacy)
    changes = CanadaLegacyImportService(session).changes(run.id)
    answer = next(item for item in changes if item.source_path == "official_review.previous_residence_over_six_months")
    host = next(item for item in changes if item.source_path == "trip.host_name")
    assert answer.proposed_value_json == "unknown" and answer.review_policy == "explicit_review"
    assert host.status == "conflict" and host.conflict_type == "confirmed_fact_contradiction"
    action = WorkflowService(session).get_next_action(case.id)
    assert action.type == "REVIEW_CANADA_IMPORT" and action.import_run_id == run.id


def test_import_does_not_transition_workflow_and_records_provenance(session):
    case, applicant, _app = setup_application(session)
    before = case.workflow_state
    legacy = CanadaCase(); legacy.identity.date_of_birth = "17/04/1992"
    run = preview(session, case, legacy)
    CanadaLegacyImportService(session).apply(run.id, mode="safe")
    session.refresh(case)
    assert case.workflow_state == before
    provenance = session.scalar(select(cm.FieldProvenanceReview).where(cm.FieldProvenanceReview.entity_type == "person_biography", cm.FieldProvenanceReview.entity_id == applicant.id, cm.FieldProvenanceReview.field_key == "date_of_birth"))
    assert provenance.source_type == "applicant_direct" and provenance.source_digest == "a" * 64


def test_representative_profile_creates_immutable_revisions_without_authorization(session):
    case, _applicant, app = setup_application(session)
    first = CanadaCase(); first.representative.family_name = "Representative"; first.representative.given_names = "Synthetic"; first.representative.email = "first@example.invalid"
    run1 = preview(session, case, first, "3" * 64); importer = CanadaLegacyImportService(session)
    for item in importer.changes(run1.id):
        if item.target_entity_type == "representative_profile": importer.review(item.id, "accept")
    importer.apply(run1.id)
    assert session.scalar(select(func.count(cm.RepresentativeProfileRevision.id))) == 1
    second = CanadaCase(); second.representative.family_name = "Representative"; second.representative.given_names = "Synthetic"; second.representative.email = "second@example.invalid"
    run2 = preview(session, case, second, "4" * 64)
    for item in importer.changes(run2.id):
        if item.target_entity_type == "representative_profile": importer.review(item.id, "accept")
    importer.apply(run2.id)
    revisions = list(session.scalars(select(cm.RepresentativeProfileRevision).order_by(cm.RepresentativeProfileRevision.revision_number)))
    assert [row.email for row in revisions] == ["first@example.invalid", "second@example.invalid"]
    assert session.scalar(select(cm.RepresentativeAuthorization).where(cm.RepresentativeAuthorization.application_id == app.id)) is None


def test_profile_upload_adapter_is_bounded_and_does_not_persist_raw_source(session):
    case, _applicant, _app = setup_application(session)
    from canada.representative_store import PROFILE_FIELDS
    values = {key: "" for key in PROFILE_FIELDS}; values.update(family_name="Profile", given_names="Synthetic")
    content = json.dumps({"format":"visa-automatic-canada-representative", "version":1, "representative":values}).encode()
    run = CanadaLegacyImportService(session).preview_upload(case.id, "representative_profile_json", content, "synthetic.canada-representative.json")
    assert run.source_hash == hashlib.sha256(content).hexdigest()
    assert not hasattr(run, "raw_content")


def test_verified_google_and_case_file_adapters_reuse_legacy_parsers(session, tmp_path):
    case, _applicant, _app = setup_application(session)
    csv_content = (Path(__file__).parents[2] / "tests/fixtures/canada_csv_synthetic.csv").read_bytes()
    google = CanadaLegacyImportService(session).preview_upload(
        case.id, "google_verified_csv", csv_content, "synthetic.csv"
    )
    assert google.source_type == "google_verified_csv"
    assert CanadaLegacyImportService(session).changes(google.id)

    legacy = CanadaCase(); legacy.identity.date_of_birth = "17/04/1992"
    path = tmp_path / "synthetic.canada-case.json"; save_case(legacy, path)
    stored = CanadaLegacyImportService(session).preview_upload(
        case.id, "canada_case_json", path.read_bytes(), path.name
    )
    assert any(item.source_path == "identity.date_of_birth" for item in CanadaLegacyImportService(session).changes(stored.id))


def test_failed_apply_rolls_back_the_complete_batch(session):
    case, applicant, _app = setup_application(session)
    legacy = CanadaCase(); legacy.identity.family_name = "Imported"; legacy.identity.date_of_birth = "not-a-date"
    run = preview(session, case, legacy, "5" * 64); importer = CanadaLegacyImportService(session)
    for item in importer.changes(run.id):
        if item.status in {"conflict", "ambiguous"}:
            importer.review(item.id, "use_imported")
    with pytest.raises(DomainValidationError):
        importer.apply(run.id)
    session.refresh(applicant)
    assert applicant.last_name == "Synthetic"
    assert session.get(cm.PersonBiography, applicant.id) is None
