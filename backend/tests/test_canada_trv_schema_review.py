from __future__ import annotations

import csv
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.api.intake import intake_storage_provider
from backend.app.database import get_session
from backend.app.main import app
from backend.app.storage import LocalStorageProvider
from backend.app.services.canada_trv_review import CanadaTrvReviewService
from backend.app.services.canada_trv_schema import CsvParser, CsvSchemaMismatch, Normalizer, SchemaRegistry
from backend.app.services.core import DomainValidationError


def csv_bytes(headers, rows):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows([headers, *rows])
    return stream.getvalue().encode("utf-8")


@pytest.fixture(scope="module")
def registry():
    return SchemaRegistry()


def source(registry, values=None, *, username=True, rows=1):
    headers = [item["csv_header"] for item in registry.fields]
    record = [""] * 235
    for field_id, value in (values or {}).items():
        record[int(field_id.split("_")[1]) - 1] = value
    if not username:
        headers = headers[:1] + headers[2:]
        record = record[:1] + record[2:]
    return csv_bytes(headers, [record[:] for _ in range(rows)])


def test_schema_contract_and_known_corrections(registry):
    assert len(registry.fields) == 235
    assert len(registry.sections) == 28
    gf114 = next(item for item in registry.fields if item["field_id"] == "GF_114")
    gf129 = next(item for item in registry.fields if item["field_id"] == "GF_129")
    assert gf114["normalized_type"] == "choice_raw"
    assert gf129["csv_header"] == "País de nascimento do genitor 1"
    assert gf129["label_pt"] == "País de nascimento do genitor 2"


@pytest.mark.parametrize(("username", "count"), [(True, 235), (False, 234)])
def test_both_exact_header_variants_and_multiple_rows(registry, username, count):
    parsed = CsvParser(registry).parse(source(registry, {"GF_003": "Silva"}, username=username, rows=2))
    assert len(parsed.headers) == count
    assert len(parsed.rows) == 2
    normalized = Normalizer(registry).normalize(parsed, parsed.rows[0], 2)
    surname = next(item for item in normalized.fields if item["field_id"] == "GF_003")
    username_field = next(item for item in normalized.fields if item["field_id"] == "GF_002")
    assert surname["raw_value"] == "Silva"
    assert username_field["review_status"] == "not_applicable"


def test_unknown_or_shifted_header_is_rejected_with_diagnostic(registry):
    headers = [item["csv_header"] for item in registry.fields]
    headers[20] = headers[20] + " changed"
    with pytest.raises(CsvSchemaMismatch) as caught:
        CsvParser(registry).parse(csv_bytes(headers, [[""] * 235]))
    assert caught.value.detail["position_1based"] == 21
    assert caught.value.detail["suggested_correction"].startswith("Register a new")


def test_conditions_arrays_files_and_raw_text_are_conservative(registry):
    parsed = CsvParser(registry).parse(source(registry, {
        "GF_083": "Sim", "GF_084": "Emprego", "GF_085": "01/01/2020",
        "GF_091": "Sim", "GF_092": "Estudo", "GF_093": "2021-01-01",
        "GF_135": "Não", "GF_198": "Brasil - turismo", "GF_216": "SIMULADO_NAO_ANEXADO",
    }))
    result = Normalizer(registry).normalize(parsed, parsed.rows[0], 2)
    assert len(result.data["activities"]) == 2
    assert [item["_source_slot"] for item in result.data["activities"]] == [1, 2]
    assert result.data["children"] == []
    assert result.data["immigration"]["travel_history"]["raw_text"] == "Brasil - turismo"
    assert result.data["immigration"]["travel_history"]["candidates"] == []
    document = result.data["documents"]["applicant"]["civil_status_certificate"]
    assert document["status"] == "simulated_placeholder"
    assert document["references"] == []


def test_security_details_three_valued_condition(registry):
    parsed = CsvParser(registry).parse(source(registry, {"GF_209": "Sim"}))
    result = Normalizer(registry).normalize(parsed, parsed.rows[0], 2)
    details = next(item for item in result.fields if item["field_id"] == "GF_213")
    assert details["applicability"] == "applicable"
    assert details["review_status"] == "missing"
    assert any(issue["field_id"] == "GF_213" for issue in result.issues)


def test_persistent_correction_confirmation_and_reload(session, registry):
    actor = SimpleNamespace(id=None, email="reviewer@example.invalid", role="ADMIN", display_name="Reviewer")
    service = CanadaTrvReviewService(session, registry)
    applications = service.import_csv(
        source(registry, {"GF_003": "Silva", "GF_004": "Ana", "GF_006": "10/02/1990"}),
        "synthetic.csv", "private/source-key", actor=actor,
    )
    application = service.get(applications[0].id)
    surname = next(item for item in application.fields if item.field_id == "GF_003")
    service.update_field(surname.id, "Souza", actor=actor)
    corrected = service._field(surname.id)
    assert corrected.raw_value == "Silva"
    assert corrected.edited_value_json == "Souza"
    assert corrected.review_status == "corrected_pending_confirmation"
    service.confirm_field(surname.id, actor=actor)
    reloaded = CanadaTrvReviewService(session, registry).get(application.id)
    saved = next(item for item in reloaded.fields if item.field_id == "GF_003")
    assert saved.review_status == "confirmed_after_correction"
    assert saved.revisions[0].old_value_json == "Silva"
    assert saved.revisions[0].new_value_json == "Souza"


def test_section_confirmation_does_not_bulk_confirm_pending_fields(session, registry):
    actor = SimpleNamespace(id=None, email="reviewer@example.invalid", role="ADMIN", display_name="Reviewer")
    service = CanadaTrvReviewService(session, registry)
    application = service.import_csv(
        source(registry, {"GF_003": "Silva"}), "synthetic.csv", "private/source-key", actor=actor,
    )[0]
    application = service.get(application.id)
    personal = [field for field in application.fields if field.section_id == "personal"]
    for field in personal:
        field.review_status = "confirmed"
    personal[0].review_status = "pending"
    application.validation_issues_json = [
        issue for issue in application.validation_issues_json if issue.get("section_id") != "personal"
    ]
    session.commit()

    with pytest.raises(DomainValidationError, match="Confirm every applicable field"):
        service.confirm_section(application.id, "personal", actor=actor)
    assert service._field(personal[0].id).review_status == "pending"


def test_multiple_response_rows_create_independent_cases(session, registry):
    actor = SimpleNamespace(id=None, email="reviewer@example.invalid", role="ADMIN", display_name="Reviewer")
    applications = CanadaTrvReviewService(session, registry).import_csv(
        source(registry, {"GF_003": "Silva"}, rows=2), "two.csv", "private/two", actor=actor,
    )
    assert len(applications) == 2
    assert applications[0].case_id != applications[1].case_id
    assert [item.import_row_number for item in applications] == [2, 3]


def test_authenticated_review_api_imports_and_reloads(session, registry, tmp_path):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[intake_storage_provider] = lambda: LocalStorageProvider(tmp_path / "review-intake")
    client = TestClient(app)
    try:
        response = client.post(
            "/canada-trv-reviews/import",
            files={"file": ("synthetic.csv", source(registry, {"GF_003": "Silva", "GF_004": "Ana"}), "text/csv")},
        )
        assert response.status_code == 201, response.text
        review_id = response.json()[0]["id"]
        detail = client.get(f"/canada-trv-reviews/{review_id}")
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["schema_version"] == "3.0.0"
        assert len(payload["fields"]) == 235
        assert payload["fields"][2]["raw_value"] == "Silva"
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(intake_storage_provider, None)
