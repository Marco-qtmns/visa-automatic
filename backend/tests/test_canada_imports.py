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
    same = next(item for item in changes if item.status == "same")
    importer = CanadaLegacyImportService(session)
    importer.apply(run.id, mode="safe")
    session.refresh(same)
    assert same.status == "same"
    assert same.reviewed_at is None


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


@pytest.mark.parametrize("source, expected", [
    ("Brasil", "BRA"), ("Brazil", "BRA"), ("Brésil", "BRA"),
    ("Brasilien", "BRA"), ("Switzerland", "CHE"), ("Schweiz", "CHE"),
    ("Canada", "CAN"), ("BRA", "BRA"),
])
def test_country_names_normalize_to_iso_alpha3_without_truncation(session, source, expected):
    case, _applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.identity.birth_country = source
    run = preview(session, case, legacy, hashlib.sha256(source.encode()).hexdigest())
    change = CanadaLegacyImportService(session).changes(run.id)[0]
    assert change.proposed_value_json == expected
    assert change.raw_value_json == source
    assert change.classification == "SAFE_NEW"


def test_unknown_country_is_preserved_for_review_and_identifies_target(session):
    case, _applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.identity.birth_country = "Atlantis"
    run = preview(session, case, legacy, "6" * 64)
    change = CanadaLegacyImportService(session).changes(run.id)[0]
    assert change.proposed_value_json == "Atlantis"
    assert change.status == "ambiguous"
    assert change.classification == "INVALID"
    assert change.target_label == "Applicant — Birth Country"


@pytest.mark.parametrize("record_key, owner", [
    ("parent:mother:1", "Mother"),
    ("parent:father:2", "Father"),
    ("spouse", "Spouse"),
])
def test_repeated_people_have_distinguishable_stable_target_labels(record_key, owner):
    item = cm.CanadaImportCandidate(
        import_run_id=uuid.uuid4(), domain_section="Family",
        employee_label="Birth country", target_entity_type="family_biography",
        target_field="birth_country_code", operation="create_or_set",
        source_path="family.members[*].birth_country", source_record_key=record_key,
        source_classification="applicant_direct", source_reference="test",
        raw_value_json="Brazil", proposed_value_json="BRA", current_value_json=None,
        status="new", review_policy="safe_direct_batch", conflict_policy="review",
    )
    assert item.target_label == f"{owner} — Birth country"


def test_unknown_alpha3_country_is_not_written_to_canonical_field(session):
    case, applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.identity.birth_country = "XYZ"
    run = preview(session, case, legacy, "8" * 64)
    importer = CanadaLegacyImportService(session)
    change = importer.changes(run.id)[0]
    assert change.raw_value_json == "XYZ"
    assert change.status == "ambiguous"
    importer.apply(run.id, mode="safe")
    assert session.get(cm.PersonBiography, applicant.id) is None


def test_safe_gate_excludes_non_direct_candidates(session):
    case, _applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.trip.purpose = "Visit"
    run = preview(session, case, legacy, "9" * 64)
    importer = CanadaLegacyImportService(session)
    item = importer.changes(run.id)[0]
    item.source_classification = "legacy_derived"
    session.commit()
    importer.apply(run.id, mode="safe")
    session.refresh(item)
    assert item.status == "new"


def test_safe_gate_excludes_unresolved_competing_candidate(session):
    case, _applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.trip.purpose = "Visit"
    run = preview(session, case, legacy, "d" * 64)
    importer = CanadaLegacyImportService(session)
    item = importer.changes(run.id)[0]
    competitor = cm.CanadaImportCandidate(
        import_run_id=run.id, domain_section=item.domain_section,
        employee_label=item.employee_label, target_entity_type=item.target_entity_type,
        target_entity_id=item.target_entity_id, target_field=item.target_field,
        operation=item.operation, source_path="staff_review.competing_purpose",
        source_record_key=item.source_record_key,
        source_classification="applicant_direct", source_reference="test:competing",
        raw_value_json="Other", proposed_value_json="Other", current_value_json=None,
        status="new", review_policy="safe_direct_batch", conflict_policy="review",
    )
    session.add(competitor)
    session.commit()
    importer.apply(run.id, mode="safe")
    session.refresh(item)
    assert item.status == "new"


def test_exact_same_csv_twice_reuses_run_and_does_not_duplicate_state(session):
    case, _applicant, _app = setup_application(session)
    content = (Path(__file__).parents[2] / "tests/fixtures/canada_csv_synthetic.csv").read_bytes()
    importer = CanadaLegacyImportService(session)
    first = importer.preview_upload(case.id, "google_verified_csv", content, "synthetic.csv")
    importer.apply(first.id, mode="safe")
    counts_after_first = {
        "persons": session.scalar(select(func.count(models.Person.id)).where(models.Person.case_id == case.id)),
        "biographies": session.scalar(select(func.count(cm.PersonBiography.person_id))),
        "activities": session.scalar(select(func.count(cm.ActivityRecord.id))),
        "travel": session.scalar(select(func.count(cm.TravelHistoryRecord.id))),
        "family": session.scalar(select(func.count(cm.FamilyRelationship.id))),
        "candidates": session.scalar(select(func.count(cm.CanadaImportCandidate.id))),
    }
    second = importer.preview_upload(case.id, "google_verified_csv", content, "synthetic.csv")
    importer.apply(second.id, mode="safe")
    assert second.id == first.id
    assert session.scalar(select(func.count(cm.CanadaLegacyImportRun.id))) == 1
    assert counts_after_first == {
        "persons": session.scalar(select(func.count(models.Person.id)).where(models.Person.case_id == case.id)),
        "biographies": session.scalar(select(func.count(cm.PersonBiography.person_id))),
        "activities": session.scalar(select(func.count(cm.ActivityRecord.id))),
        "travel": session.scalar(select(func.count(cm.TravelHistoryRecord.id))),
        "family": session.scalar(select(func.count(cm.FamilyRelationship.id))),
        "candidates": session.scalar(select(func.count(cm.CanadaImportCandidate.id))),
    }


def test_retry_after_failed_apply_has_no_partial_duplicate_state(session):
    case, applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.identity.family_name = "Imported"
    legacy.identity.date_of_birth = "not-a-date"
    run = preview(session, case, legacy, "b" * 64)
    importer = CanadaLegacyImportService(session)
    for item in importer.changes(run.id):
        if item.status in {"conflict", "ambiguous"}:
            importer.review(item.id, "use_imported")
    with pytest.raises(DomainValidationError):
        importer.apply(run.id)
    bad_date = next(item for item in importer.changes(run.id) if item.source_path == "identity.date_of_birth")
    importer.review(bad_date.id, "reject")
    importer.apply(run.id)
    assert session.get(models.Person, applicant.id).last_name == "Imported"
    assert session.scalar(select(func.count(cm.PersonBiography.person_id)).where(cm.PersonBiography.person_id == applicant.id)) == 0


def test_low_level_apply_failure_is_sanitized_and_transactional(session, monkeypatch):
    case, applicant, _app = setup_application(session)
    legacy = CanadaCase()
    legacy.identity.family_name = "Imported"
    run = preview(session, case, legacy, "c" * 64)
    importer = CanadaLegacyImportService(session)
    change = importer.changes(run.id)[0]
    importer.review(change.id, "use_imported")
    monkeypatch.setattr(importer, "_apply_candidate", lambda *_args: (_ for _ in ()).throw(RuntimeError("SELECT secret FROM users password=leak")))
    with pytest.raises(DomainValidationError) as captured:
        importer.apply(run.id)
    assert captured.value.api_detail == {
        "code": "IMPORT_APPLY_FAILED",
        "message": "Import could not be applied.",
        "issues": ["Review the highlighted value and try again."],
    }
    assert "SELECT" not in str(captured.value.api_detail)
    session.refresh(applicant)
    assert applicant.last_name == "Synthetic"


def test_source_first_import_can_identify_an_unnamed_case(session):
    case = models.Case(case_number="CA-SOURCE-FIRST", visa_type="canada_trv", purpose="To be confirmed")
    session.add(case)
    session.commit()
    legacy = CanadaCase()
    legacy.identity.given_names = "Amina"
    legacy.identity.family_name = "Diallo"
    importer = CanadaLegacyImportService(session)
    run = importer.preview_case(
        case.id, legacy, source_type="google_verified_csv",
        source_identifier="synthetic.csv", source_hash="7" * 64,
    )
    importer.apply(run.id, mode="safe", reviewed_by="worker")
    applicant = session.scalar(select(models.Person).where(models.Person.case_id == case.id))
    application = session.scalar(select(cm.CanadaApplication).where(cm.CanadaApplication.case_id == case.id))
    assert (applicant.first_name, applicant.last_name, applicant.roles) == ("Amina", "Diallo", ["applicant"])
    assert application.applicant_person_id == applicant.id
