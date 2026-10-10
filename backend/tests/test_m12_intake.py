from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from canada.models import CanadaCase
from backend.app import models
from backend.app.api.intake import intake_storage_provider
from backend.app.auth import require_authenticated_request
from backend.app.config.canada_import_mapping import MAPPING_VERSION
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models import canada as cm
from backend.app.models.audit import ApplicationAuditEvent
from backend.app.models.intake import IntakeProcessingAttempt, IntakeSubmission
from backend.app.schemas.canada import CanadaApplicationCreate
from backend.app.schemas.core import CaseCreate
from backend.app.services.canada import CanadaApplicationService
from backend.app.services.canada_imports import CanadaLegacyImportService
from backend.app.services.intake import ADAPTERS, GOOGLE_FORMS_CSV, IntakeService
from backend.app.services.requirements import CaseApplicationService
from backend.app.storage import LocalStorageProvider


FIXTURE = Path(__file__).parents[2] / "tests/fixtures/canada_20260929_synthetic.csv"


def minimal_csv(family_name="Diallo", given_names="Amina") -> bytes:
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
    values = [""] * len(rows[0])
    values[0] = "2026-10-07 10:00:00"
    values[1] = family_name
    values[2] = given_names
    output = io.StringIO(newline="")
    csv.writer(output).writerows([rows[0], values])
    return output.getvalue().encode("utf-8-sig")


def full_family_csv() -> bytes:
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
    values = [""] * len(rows[0])
    values[0] = "2026-10-07 11:00:00"
    values[1:3] = ["Diallo", "Amina"]
    values[16:20] = ["Costa", "Lucia", "02/03/1985", "Brasil"]
    values[24:27] = ["Former", "Franca", "03/04/1980"]
    values[113:118] = ["Almeida", "João Roberto", "04/05/1960", "Dakar", "Brasil"]
    values[123:128] = ["Costa", "Lúcia Helena", "05/06/1958", "Dakar", "Brasil"]
    values[134:141] = ["Biological", "Diallo", "Noah", "06/07/2015", "Single", "Zurich", "Brasil"]
    output = io.StringIO(newline="")
    csv.writer(output).writerows([rows[0], values])
    return output.getvalue().encode("utf-8-sig")


def host_csv() -> bytes:
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
    values = [""] * len(rows[0])
    values[0:3] = ["2026-10-09 10:00:00", "Diallo", "Amina"]
    values[60:66] = [
        "Pessoa", "Ana Silva", "Friend", "", "Permanent resident",
        "123 King Street, Toronto, ON, M5V 2T6",
    ]
    output = io.StringIO(newline="")
    csv.writer(output).writerows([rows[0], values])
    return output.getvalue().encode("utf-8-sig")


@pytest.fixture
def intake(session, tmp_path):
    storage = LocalStorageProvider(tmp_path / "intake")
    actor = SimpleNamespace(
        id=None, email="worker@example.invalid", role="CASE_WORKER",
        display_name="Worker", is_active=True,
    )
    return IntakeService(session, storage), storage, actor


def create_empty_case(session, actor, number=None):
    return CaseApplicationService(session).create_case(
        CaseCreate(case_number=number), audit_actor=actor
    )


def link_applicant(session, case, first="Amina", last="Diallo"):
    applicant = models.Person(
        case_id=case.id, first_name=first, last_name=last, roles=["applicant"]
    )
    session.add(applicant)
    session.commit()
    CanadaApplicationService(session).create_application(
        case.id, CanadaApplicationCreate(applicant_person_id=applicant.id)
    )
    return applicant


def test_submission_creates_case_applies_safe_identity_preserves_raw_and_audits(session, intake):
    service, storage, actor = intake
    content = minimal_csv()
    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=content,
        filename="submission.csv", source_external_id="google-001", actor=actor,
    )
    assert result.processing_status == "PROCESSED"
    assert result.case_id is not None and result.issue_count == 0
    assert result.applicant_display_name == "Amina Diallo"
    assert storage.exists(result.raw_source_reference)
    with storage.open(result.raw_source_reference) as stored:
        assert stored.read() == content
    applicant = session.scalar(select(models.Person).where(models.Person.case_id == result.case_id))
    assert (applicant.first_name, applicant.last_name) == ("Amina", "Diallo")
    assert {event.action for event in session.scalars(select(ApplicationAuditEvent))} >= {
        "INTAKE_RECEIVED", "INTAKE_PROCESSED", "CASE_CREATED",
    }


def test_duplicate_submission_is_idempotent_and_same_has_no_work(session, intake):
    service, _storage, actor = intake
    content = minimal_csv()
    first = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=content,
        filename="submission.csv", source_external_id="google-duplicate", actor=actor,
    )
    case_count = session.scalar(select(func.count(models.Case.id)))
    person_count = session.scalar(select(func.count(models.Person.id)))
    candidate_count = session.scalar(select(func.count(cm.CanadaImportCandidate.id)))
    second = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=content,
        filename="renamed.csv", source_external_id="google-duplicate", actor=actor,
    )
    assert second.id == first.id
    assert second.duplicate_receive_count == 1
    assert session.scalar(select(func.count(models.Case.id))) == case_count == 1
    assert session.scalar(select(func.count(models.Person.id))) == person_count == 1
    assert session.scalar(select(func.count(cm.CanadaImportCandidate.id))) == candidate_count
    assert session.scalar(select(func.count(IntakeProcessingAttempt.id))) == 1


def test_concurrent_duplicate_intake_uses_database_identity(session, tmp_path):
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    storage = LocalStorageProvider(tmp_path / "concurrent-intake")
    actor = SimpleNamespace(
        id=None, email="worker@example.invalid", role="CASE_WORKER",
        display_name="Worker", is_active=True,
    )
    content = minimal_csv()
    barrier = Barrier(2)

    def receive():
        with factory() as worker_session:
            barrier.wait()
            result = IntakeService(worker_session, storage).receive_and_process(
                source_type=GOOGLE_FORMS_CSV, content=content,
                filename="concurrent.csv", source_external_id="concurrent-001", actor=actor,
            )
            return result.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _index: receive(), range(2)))
    session.expire_all()
    assert len(set(ids)) == 1
    assert session.scalar(select(func.count(IntakeSubmission.id))) == 1
    assert session.scalar(select(func.count(models.Case.id))) == 1
    assert session.scalar(select(func.count(models.Person.id))) == 1


def test_submission_can_feed_an_unidentified_existing_case(session, intake):
    service, _storage, actor = intake
    case = create_empty_case(session, actor)
    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=minimal_csv(), filename="existing.csv",
        requested_case_id=case.id, actor=actor,
    )
    assert result.case_id == case.id
    assert result.applicant_display_name == "Amina Diallo"
    assert session.scalar(select(func.count(models.Case.id))) == 1
    attempt = service.attempts(result.id)[0]
    assert attempt.matched_existing_case == 1 and attempt.created_case == 0
    assert service.metrics()["new_cases_created"] == 0
    assert service.metrics()["existing_cases_matched"] == 1


def test_external_identity_matches_one_prior_case_without_name_guessing(session, intake):
    service, storage, actor = intake
    case = create_empty_case(session, actor)
    stored = storage.save(io.BytesIO(b"prior"), max_bytes=100)
    session.add(IntakeSubmission(
        source_type=GOOGLE_FORMS_CSV, source_external_id="stable-google-id",
        source_filename="prior.csv", source_hash="1" * 64, source_size_bytes=5,
        raw_source_reference=stored.key, mapping_version="older-mapping",
        processing_status="PROCESSED", case_id=case.id,
    ))
    session.commit()
    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=minimal_csv(), filename="current.csv",
        source_external_id="stable-google-id", actor=actor,
    )
    assert result.case_id == case.id
    assert session.scalar(select(func.count(models.Case.id))) == 1


def test_ambiguous_external_case_links_never_merge(session, intake):
    service, storage, actor = intake
    first = create_empty_case(session, actor, "AMBIGUOUS-1")
    second = create_empty_case(session, actor, "AMBIGUOUS-2")
    for index, case in enumerate((first, second), start=1):
        stored = storage.save(io.BytesIO(f"prior-{index}".encode()), max_bytes=100)
        session.add(IntakeSubmission(
            source_type=GOOGLE_FORMS_CSV, source_external_id="ambiguous-id",
            source_filename=f"prior-{index}.csv", source_hash=str(index) * 64,
            source_size_bytes=7, raw_source_reference=stored.key,
            mapping_version=f"older-{index}", processing_status="PROCESSED", case_id=case.id,
        ))
    session.commit()
    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=minimal_csv(), filename="current.csv",
        source_external_id="ambiguous-id", actor=actor,
    )
    assert result.processing_status == "NEEDS_REVIEW"
    assert result.failure_code == "AMBIGUOUS_CASE_MATCH"
    assert result.case_id is None
    assert session.scalar(select(func.count(models.Case.id))) == 2
    resolved = service.retry(result.id, requested_case_id=first.id, actor=actor)
    assert resolved.case_id == first.id
    assert resolved.processing_status == "PROCESSED"
    assert session.scalar(select(func.count(models.Case.id))) == 2


def test_same_is_suppressed_and_conflict_becomes_intake_exception(session, intake):
    service, _storage, actor = intake
    same_case = create_empty_case(session, actor, "SAME-CASE")
    link_applicant(session, same_case)
    same = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=minimal_csv(), filename="same.csv",
        requested_case_id=same_case.id, actor=actor,
    )
    assert same.processing_status == "PROCESSED" and same.issue_count == 0
    assert all(item.status == "same" for item in cm_changes(session, same.import_run_id))

    conflict_case = create_empty_case(session, actor, "CONFLICT-CASE")
    original = link_applicant(session, conflict_case, last="Original")
    conflict = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=minimal_csv(family_name="Different"), filename="conflict.csv",
        requested_case_id=conflict_case.id, source_external_id="conflict-source", actor=actor,
    )
    assert conflict.processing_status == "NEEDS_REVIEW" and conflict.issue_count == 1
    session.refresh(original)
    assert original.last_name == "Original"
    assert any(item.status == "conflict" for item in cm_changes(session, conflict.import_run_id))


def cm_changes(session, import_run_id):
    return list(session.scalars(select(cm.CanadaImportCandidate).where(
        cm.CanadaImportCandidate.import_run_id == import_run_id
    )))


def test_invalid_source_fails_safely_and_retry_after_parser_fix_is_idempotent(session, intake, monkeypatch):
    service, storage, actor = intake
    raw = b"not,a,known,schema\ninvalid"
    failed = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=raw, filename="invalid.csv", actor=actor,
    )
    assert failed.processing_status == "FAILED"
    assert failed.failure_code == "UNSUPPORTED_GOOGLE_FORMS_SCHEMA"
    assert failed.failure_detail_json["field_path"] == "source_file"
    assert "schema" not in failed.failure_message.casefold()
    with storage.open(failed.raw_source_reference) as source:
        assert source.read() == raw

    parsed = CanadaCase()
    parsed.identity.family_name = "Diallo"
    parsed.identity.given_names = "Amina"
    monkeypatch.setattr(ADAPTERS[GOOGLE_FORMS_CSV], "parse_source", lambda _content, _filename: parsed)
    retried = service.retry(failed.id, actor=actor)
    assert retried.processing_status == "PROCESSED"
    assert retried.retry_count == 1
    assert session.scalar(select(func.count(models.Case.id))) == 1
    assert session.scalar(select(func.count(models.Person.id))) == 1
    assert len(service.attempts(failed.id)) == 2
    with storage.open(retried.raw_source_reference) as source:
        assert source.read() == raw


def test_downstream_apply_failure_is_classified_and_retry_reuses_created_case(
    session, intake, monkeypatch
):
    service, storage, actor = intake
    original_apply = CanadaLegacyImportService.apply
    calls = 0

    def fail_once(importer, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic database detail that must not reach the employee")
        return original_apply(importer, *args, **kwargs)

    monkeypatch.setattr(CanadaLegacyImportService, "apply", fail_once)
    failed = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=minimal_csv(),
        filename="apply-failure.csv", actor=actor,
    )
    assert failed.processing_status == "FAILED"
    assert failed.failure_code == "IMPORT_APPLY_FAILED"
    assert "database" not in failed.failure_message.casefold()
    retained_case_id = failed.case_id
    retained_reference = failed.raw_source_reference
    assert retained_case_id is not None

    retried = service.retry(failed.id, actor=actor)
    assert retried.processing_status == "PROCESSED"
    assert retried.case_id == retained_case_id
    assert retried.raw_source_reference == retained_reference
    assert retried.retry_count == 1
    assert retried.duplicate_receive_count == 0
    attempts = service.attempts(failed.id)
    assert [attempt.attempt_number for attempt in attempts] == [2, 1]
    assert all(not (attempt.created_case and attempt.matched_existing_case) for attempt in attempts)
    assert session.scalar(select(func.count(models.Case.id))) == 1
    assert session.scalar(select(func.count(models.Person.id))) == 1
    assert service.metrics()["new_cases_created"] == 1
    assert service.metrics()["existing_cases_matched"] == 0
    with storage.open(retained_reference) as source:
        assert source.read() == minimal_csv()


def test_verified_google_family_country_end_to_end_preserves_raw_and_applies_iso(session, intake):
    service, _storage, actor = intake
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
    values = [""] * len(rows[0])
    values[0] = "2026-10-07 10:00:00"
    values[1] = "Diallo"
    values[2] = "Amina"
    values[16] = "Costa"
    values[17] = "Lucia"
    values[19] = "Brasil"
    output = io.StringIO(newline="")
    csv.writer(output).writerows([rows[0], values])
    content = output.getvalue().encode("utf-8-sig")

    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=content,
        filename="google-family-country.csv", actor=actor,
    )
    assert result.processing_status == "PROCESSED"
    change = session.scalar(select(cm.CanadaImportCandidate).where(
        cm.CanadaImportCandidate.import_run_id == result.import_run_id,
        cm.CanadaImportCandidate.source_path == "relationships.spouse_birth_country",
    ))
    assert change.raw_value_json == "Brasil"
    assert change.proposed_value_json == "BRA"
    applicant = next(
        person for person in session.scalars(select(models.Person).where(
            models.Person.case_id == result.case_id,
        )) if "applicant" in person.roles
    )
    family_biographies = [
        row for row in session.scalars(select(cm.PersonBiography))
        if row.person_id != applicant.id
    ]
    assert [row.birth_country_code for row in family_biographies] == ["BRA"]


def test_verified_google_host_review_applies_without_generic_database_failure(session, intake):
    service, _storage, actor = intake
    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=host_csv(),
        filename="google-host.csv", actor=actor,
    )
    assert result.processing_status == "NEEDS_REVIEW"
    importer = CanadaLegacyImportService(session)
    changes = importer.changes(result.import_run_id)
    for item in changes:
        if item.conflict_type == "host_type_ambiguous":
            importer.review(item.id, "use_imported", actor.email, host_type="person")
        elif item.status == "new":
            importer.review(item.id, "accept", actor.email)
    importer.apply(result.import_run_id, reviewed_by=actor.email)
    host = session.scalar(select(cm.HostRecord))
    assert host.host_type == "person"
    assert session.get(cm.Address, host.address_id).postal_code == "M5V 2T6"


def test_full_google_family_import_keeps_roles_and_relationships_separate(session, intake):
    service, _storage, actor = intake
    result = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV,
        content=full_family_csv(),
        filename="google-full-family.csv",
        actor=actor,
    )
    assert result.processing_status == "PROCESSED"
    people = list(session.scalars(select(models.Person).where(
        models.Person.case_id == result.case_id
    )))
    assert len(people) == 6
    valid_roles = {role.value for role in cm.OperationalRole}
    assert all(set(person.roles) <= valid_roles for person in people)
    assert all("family_member" not in person.roles for person in people)
    assert not any(
        person.first_name == "Pending review" or person.last_name == "Pending review"
        for person in people
    )
    relationships = list(session.scalars(select(cm.FamilyRelationship).join(
        cm.CanadaApplication,
        cm.CanadaApplication.id == cm.FamilyRelationship.application_id,
    ).where(cm.CanadaApplication.case_id == result.case_id)))
    assert [item.relationship_type for item in relationships].count("spouse") == 1
    assert [item.relationship_type for item in relationships].count("former_spouse") == 1
    assert [item.relationship_type for item in relationships].count("parent") == 2
    assert [item.relationship_type for item in relationships].count("child") == 1
    people_by_id = {person.id: person for person in people}
    relationships_by_name = {
        people_by_id[item.related_person_id].first_name: item
        for item in relationships
    }
    assert relationships_by_name["João Roberto"].parent_type == "father"
    assert relationships_by_name["Lúcia Helena"].parent_type == "mother"
    assert relationships_by_name["Lucia"].relationship_type == "spouse"
    assert relationships_by_name["Lucia"].is_current is True
    assert relationships_by_name["Franca"].relationship_type == "former_spouse"
    assert relationships_by_name["Franca"].is_current is False
    assert relationships_by_name["Noah"].relationship_type == "child"
    assert all(
        item.is_current is False
        for item in relationships
        if item.relationship_type in {"parent", "child", "former_spouse"}
    )
    assert all(
        people_by_id[item.related_person_id].roles == ["other"]
        for item in relationships
    )

    app.dependency_overrides[get_session] = _session_override(session)
    try:
        response = TestClient(app).get(f"/cases/{result.case_id}/persons")
        assert response.status_code == 200
        assert all(set(person["roles"]) <= valid_roles for person in response.json())
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_stale_verified_intake_reprocess_repairs_parent_roles_without_duplicates(
    session, intake
):
    service, _storage, actor = intake
    original = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV,
        content=full_family_csv(),
        filename="google-family-stale.csv",
        actor=actor,
    )
    original_run = session.get(cm.CanadaLegacyImportRun, original.import_run_id)
    original_run.mapping_version = "m9b-2"
    original.mapping_version = "m9b-2"
    for attempt in service.attempts(original.id):
        attempt.mapping_version = "m9b-2"
    parent_relationships = list(session.scalars(select(cm.FamilyRelationship).where(
        cm.FamilyRelationship.relationship_type == "parent"
    ).order_by(cm.FamilyRelationship.sort_order)))
    for index, relationship in enumerate(parent_relationships, start=1):
        relationship.parent_type = None
        for link in session.scalars(select(cm.LegacyImportEntityLink).where(
            cm.LegacyImportEntityLink.case_id == original.case_id,
            cm.LegacyImportEntityLink.source_record_key.in_({
                f"parent:father:{index}", f"parent:mother:{index}",
            }),
        )):
            link.source_record_key = f"parent:parent:{index}"
    session.commit()

    assert service.get(original.id).can_retry is True
    person_count = session.scalar(select(func.count(models.Person.id)))
    relationship_count = session.scalar(select(func.count(cm.FamilyRelationship.id)))
    repaired = service.retry(original.id, actor=actor)

    assert repaired.processing_status == "PROCESSED"
    assert repaired.can_retry is False
    assert session.scalar(select(func.count(models.Person.id))) == person_count
    assert session.scalar(select(func.count(cm.FamilyRelationship.id))) == relationship_count
    repaired_parents = list(session.scalars(select(cm.FamilyRelationship).where(
        cm.FamilyRelationship.relationship_type == "parent"
    ).order_by(cm.FamilyRelationship.sort_order)))
    assert [item.parent_type for item in repaired_parents] == ["father", "mother"]
    parent_link_keys = set(session.scalars(select(
        cm.LegacyImportEntityLink.source_record_key
    ).where(
        cm.LegacyImportEntityLink.case_id == original.case_id,
        cm.LegacyImportEntityLink.canonical_entity_type == "family_relationship",
        cm.LegacyImportEntityLink.source_record_key.like("parent:%"),
    )))
    assert parent_link_keys == {"parent:father:1", "parent:mother:2"}
    assert len(service.attempts(original.id)) == 2


def test_failed_full_family_intake_retry_reuses_case_and_canonical_entities(
    session, intake, monkeypatch
):
    service, _storage, actor = intake
    original_apply = CanadaLegacyImportService.apply
    calls = 0

    def fail_once(importer, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic transient apply failure")
        return original_apply(importer, *args, **kwargs)

    monkeypatch.setattr(CanadaLegacyImportService, "apply", fail_once)
    failed = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=full_family_csv(),
        filename="google-full-family-retry.csv", actor=actor,
    )
    case_id = failed.case_id
    assert failed.processing_status == "FAILED" and case_id is not None
    retried = service.retry(failed.id, actor=actor)
    assert retried.id == failed.id and retried.case_id == case_id
    assert [attempt.attempt_number for attempt in service.attempts(failed.id)] == [2, 1]
    assert session.scalar(select(func.count(models.Case.id))) == 1
    assert session.scalar(select(func.count(models.Person.id))) == 6
    assert session.scalar(select(func.count(cm.FamilyRelationship.id))) == 5


def test_intake_metrics_track_operational_outcomes(session, intake):
    service, _storage, actor = intake
    content = minimal_csv()
    first = service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=content, filename="metric.csv", actor=actor,
    )
    service.receive_and_process(
        source_type=GOOGLE_FORMS_CSV, content=content, filename="metric-copy.csv", actor=actor,
    )
    metrics = service.metrics()
    assert metrics == {
        "submissions_received": 1,
        "successfully_processed": 1,
        "duplicates_ignored": 1,
        "new_cases_created": 1,
        "existing_cases_matched": 0,
        "review_required": 0,
        "failed": 0,
    }
    assert first.processing_status == "PROCESSED"


def _session_override(session):
    def override():
        yield session
    return override


def test_intake_api_queue_and_retry_are_role_protected(session, tmp_path):
    storage = LocalStorageProvider(tmp_path / "api-intake")
    user = SimpleNamespace(
        id=None, email="worker@example.invalid", display_name="Worker",
        role="CASE_WORKER", is_active=True, mfa_enabled=True,
    )
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[require_authenticated_request] = lambda: user
    app.dependency_overrides[intake_storage_provider] = lambda: storage
    try:
        client = TestClient(app)
        created = client.post(
            "/intake/submissions/google-forms-csv",
            data={"source_external_id": "api-001"},
            files={"file": ("submission.csv", minimal_csv(), "text/csv")},
        )
        assert created.status_code == 201 and created.json()["processing_status"] == "PROCESSED"
        assert "source_hash" not in created.json()
        assert "raw_source_reference" not in created.json()
        queue = client.get("/intake/submissions")
        assert queue.status_code == 200 and len(queue.json()) == 1
        metrics = client.get("/intake/metrics")
        assert metrics.status_code == 200 and metrics.json()["successfully_processed"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.real_auth
def test_unauthorized_intake_access_is_denied(session, tmp_path):
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[intake_storage_provider] = lambda: LocalStorageProvider(tmp_path / "unauthorized")
    try:
        client = TestClient(app)
        assert client.get("/intake/submissions").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_reviewer_has_no_intake_permission(session, tmp_path):
    reviewer = SimpleNamespace(
        id=uuid.uuid4(), email="reviewer@example.invalid", display_name="Reviewer",
        role="REVIEWER", is_active=True, mfa_enabled=True,
    )
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[require_authenticated_request] = lambda: reviewer
    app.dependency_overrides[intake_storage_provider] = lambda: LocalStorageProvider(tmp_path / "reviewer")
    try:
        assert TestClient(app).get("/intake/submissions").status_code == 403
    finally:
        app.dependency_overrides.clear()
