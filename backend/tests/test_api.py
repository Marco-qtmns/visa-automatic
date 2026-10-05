from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.database import get_session
from backend.app.main import app, configured_cors_origins
from backend.app import health as health_module


def test_cors_allows_configured_employee_frontend():
    client = TestClient(app)
    response = client.options(
        "/cases",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_origins_are_environment_configurable(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://employee.example, https://backup.example")
    assert configured_cors_origins() == [
        "https://employee.example",
        "https://backup.example",
    ]


def test_deployment_health_is_component_based_and_redacts_errors(monkeypatch):
    monkeypatch.setattr(health_module, "_database_check", lambda: {"status": "ok", "revision": health_module.EXPECTED_SCHEMA_REVISION})
    monkeypatch.setattr(health_module, "_storage_check", lambda: {"status": "ok"})
    monkeypatch.setattr(health_module, "_generator_check", lambda: {"status": "ok"})
    ready, payload = health_module.deployment_readiness()
    assert ready is True and payload["status"] == "ready"

    monkeypatch.setattr(health_module, "_database_check", lambda: (_ for _ in ()).throw(RuntimeError("secret-db-host")))
    ready, payload = health_module.deployment_readiness()
    assert ready is False
    assert payload["components"]["database"] == {"status": "error", "code": "database_unavailable"}


def test_crud_api_for_all_entities(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        case_response = client.post("/cases", json={
            "case_number": "CA-API-001", "visa_type": "TRV", "purpose": "family_visit"
        })
        assert case_response.status_code == 201
        case_id = case_response.json()["id"]
        assert client.get("/cases").json()[0]["case_number"] == "CA-API-001"
        assert client.patch(f"/cases/{case_id}", json={"purpose": "tourism"}).json()["purpose"] == "tourism"

        person = client.post(f"/cases/{case_id}/persons", json={
            "first_name": "Maria", "last_name": "Silva", "roles": ["applicant", "sponsor"]
        })
        assert person.status_code == 201
        person_id = person.json()["id"]
        assert client.get(f"/persons/{person_id}").json()["roles"] == ["applicant", "sponsor"]
        assert len(client.get(f"/cases/{case_id}/persons").json()) == 1

        fact = client.post(f"/cases/{case_id}/facts", json={
            "person_id": person_id, "key": "sponsor.exists", "value_json": True,
            "source_type": "manual", "source_reference": "employee", "status": "confirmed"
        })
        assert fact.status_code == 201
        fact_id = fact.json()["id"]
        assert client.patch(f"/facts/{fact_id}", json={"status": "proposed"}).json()["status"] == "proposed"
        assert len(client.get(f"/cases/{case_id}/facts").json()) == 1

        requirement = client.post(f"/cases/{case_id}/requirements", json={
            "document_type": "passport_bio_page", "owner_role": "applicant", "owner_person_id": person_id,
            "requirement_level": "required", "reason": "Manual requirement", "is_blocking": True
        })
        assert requirement.status_code == 201
        requirement_id = requirement.json()["id"]
        assert client.patch(f"/requirements/{requirement_id}", json={"active": False}).json()["active"] is False
        requirements = client.get(f"/cases/{case_id}/requirements").json()
        assert any(item["id"] == requirement_id for item in requirements)
        assert any(item["rule_id"] == "TRV_BASE_INTERNAL_001" for item in requirements)

        document = client.post(f"/cases/{case_id}/documents", json={
            "person_id": person_id, "original_filename": "passport.pdf", "storage_path": "case/passport.pdf",
            "mime_type": "application/pdf", "source_type": "manual_upload", "metadata_json": {"pages": 1}
        })
        assert document.status_code == 201
        document_id = document.json()["id"]
        updated = client.patch(
            f"/documents/{document_id}", json={"document_type": "passport_bio_page"}
        )
        assert updated.json()["document_type"] == "passport_bio_page"
        assert "storage_path" not in updated.json()
        assert len(client.get(f"/cases/{case_id}/documents").json()) == 1

        task = client.post(f"/cases/{case_id}/tasks", json={
            "type": "review", "title": "Review passport", "related_requirement_id": requirement_id,
            "related_document_id": document_id, "blocking": True
        })
        assert task.status_code == 201
        task_id = task.json()["id"]
        assert client.patch(f"/tasks/{task_id}", json={"status": "completed"}).json()["status"] == "completed"
        assert len(client.get(f"/cases/{case_id}/tasks").json()) == 1
        assert client.get("/health").json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_api_rejects_cross_case_relationships(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        first = client.post("/cases", json={"case_number": "CA-1", "visa_type": "TRV", "purpose": "visit"}).json()
        second = client.post("/cases", json={"case_number": "CA-2", "visa_type": "TRV", "purpose": "visit"}).json()
        person = client.post(f"/cases/{first['id']}/persons", json={
            "first_name": "A", "last_name": "B", "roles": ["applicant"]
        }).json()
        response = client.post(f"/cases/{second['id']}/facts", json={
            "person_id": person["id"], "key": "x", "value_json": 1,
            "source_type": "manual", "source_reference": "employee", "status": "confirmed"
        })
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
