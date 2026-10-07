from __future__ import annotations

import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.app.auth import create_user, require_authenticated_request
from backend.app.api.core import storage_provider
from backend.app.database import get_session
from backend.app.main import app
from backend.app import models
from backend.app.services.operational import OperationalCaseService, classify_work_queue
from backend.app.storage import LocalStorageProvider


def _session_override(session):
    def override():
        yield session
    return override


def test_empty_application_and_authenticated_bootstrap_projection(session):
    user = create_user(
        session, email="worker@example.invalid", display_name="Worker",
        password="ValidPassword123", role="CASE_WORKER",
    )
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[require_authenticated_request] = lambda: user
    try:
        client = TestClient(app)
        created = client.post("/cases", json={})
        assert created.status_code == 201
        case = created.json()
        assert re.fullmatch(r"CA-\d{4}-\d{8}", case["case_number"])
        assert case["visa_type"] == "canada_trv"

        bootstrap = client.get("/app/bootstrap")
        assert bootstrap.status_code == 200
        assert "db;dur=" in bootstrap.headers["server-timing"]
        payload = bootstrap.json()
        assert payload["user"]["email"] == "worker@example.invalid"
        assert payload["case_summary"][0]["display_name"] == "Applicant not identified yet"
        assert payload["case_summary"][0]["case_number"] == case["case_number"]

        person = client.post(f"/cases/{case['id']}/persons", json={
            "first_name": "Amina", "last_name": "Diallo", "roles": ["applicant"]
        })
        assert person.status_code == 201
        assert client.get("/app/bootstrap").json()["case_summary"][0]["display_name"] == "Amina Diallo"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.real_auth
def test_bootstrap_rejects_an_invalid_session(session):
    app.dependency_overrides[get_session] = _session_override(session)
    try:
        response = TestClient(app).get("/app/bootstrap")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_documents_and_whatsapp_can_arrive_before_applicant_identity(session, tmp_path):
    user = create_user(
        session, email="source-first@example.invalid", display_name="Source First",
        password="ValidPassword123", role="CASE_WORKER",
    )
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[require_authenticated_request] = lambda: user
    app.dependency_overrides[storage_provider] = lambda: LocalStorageProvider(tmp_path / "documents")
    try:
        client = TestClient(app)
        case = client.post("/cases", json={}).json()
        document = client.post(
            f"/cases/{case['id']}/documents/upload",
            files={"file": ("passport.pdf", b"%PDF-1.4\n% synthetic\n%%EOF\n", "application/pdf")},
        )
        conversation = client.post(
            f"/cases/{case['id']}/conversations/whatsapp/paste",
            json={"text": "01/10/2026, 10:00 - Client: I will send my passport."},
        )
        assert document.status_code == 201
        assert conversation.status_code == 201
        assert client.get(f"/cases/{case['id']}/persons").json() == []
        summary = client.get("/app/bootstrap").json()["case_summary"][0]
        assert summary["display_name"] == "Applicant not identified yet"
    finally:
        app.dependency_overrides.clear()


def test_work_queue_precedence_is_deterministic():
    assert classify_work_queue(models.WorkflowState.REVIEW, 4) == "REVIEW"
    assert classify_work_queue(models.WorkflowState.READY, 4) == "READY"
    assert classify_work_queue(models.WorkflowState.PREPARE, 1) == "ACTION_REQUIRED"
    assert classify_work_queue(models.WorkflowState.SUBMITTED, 0) == "WAITING"


def test_fifty_case_projection_returns_one_summary_per_case(session):
    session.add_all([
        models.Case(
            case_number=f"CA-LIST-{index:04d}", visa_type="canada_trv",
            purpose="Projection test",
        )
        for index in range(50)
    ])
    session.commit()
    statements: list[str] = []
    listener = lambda _connection, _cursor, statement, _parameters, _context, _many: statements.append(statement)
    event.listen(session.get_bind(), "before_cursor_execute", listener)
    try:
        summaries, _elapsed = OperationalCaseService(session).case_summaries()
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", listener)
    assert len(summaries) == 50
    assert len({summary.id for summary in summaries}) == 50
    assert all(summary.display_name == "Applicant not identified yet" for summary in summaries)
    assert len(statements) == 2
