from __future__ import annotations

import base64
from datetime import timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.app import models
from backend.app.auth import create_user, now_utc, totp_code
from backend.app.authorization import (
    ENDPOINT_PERMISSIONS,
    Permission,
    RouteAuthorizationClass,
    enforce_workflow_target,
    permissions_for_role,
    route_authorization_class,
)
from backend.app.database import get_session
from backend.app.database import Base
from backend.app.main import app
from backend.app.models.audit import ApplicationAuditEvent
from backend.app.models.auth import AuthSession, MfaChallenge, UserRole
from backend.app.services.audit import record_audit
from backend.app.deployment_preflight import PROJECT_ROOT


pytestmark = pytest.mark.real_auth
PASSWORD = "ValidPassword123"


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch):
    monkeypatch.setenv(
        "MFA_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"m10b-test-encryption-key-0000000").decode(),
    )
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")


@pytest.fixture
def client(session):
    def override_session():
        yield session
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()


def enroll(client, session, email: str, role: str):
    user = create_user(
        session, email=email, display_name=email.split("@")[0], password=PASSWORD, role=role
    )
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()
    response = client.post("/auth/mfa/verify", json={
        "challenge_token": login["challenge_token"],
        "code": totp_code(login["enrollment_secret"]),
    })
    assert response.status_code == 200
    return user


def auth_headers(client):
    return {"X-CSRF-Token": client.cookies.get("va_csrf")}


def test_permission_matrix_is_static_and_role_ordered():
    worker = permissions_for_role(UserRole.CASE_WORKER)
    reviewer = permissions_for_role(UserRole.REVIEWER)
    admin = permissions_for_role(UserRole.ADMIN)
    assert Permission.PREPARATION_RUN in worker
    assert Permission.WORKFLOW_REVIEW not in worker
    assert Permission.WORKFLOW_SUBMIT not in worker
    assert {Permission.WORKFLOW_REVIEW, Permission.WORKFLOW_SUBMIT, Permission.CASE_AUDIT_READ} <= reviewer
    assert Permission.USER_EDIT not in reviewer
    assert admin == frozenset(Permission)


def test_effective_fastapi_graph_has_exact_business_classification():
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif hasattr(route, "effective_route_contexts"):
            routes.extend(route.effective_route_contexts())
    identities_by_name: dict[str, set[tuple[str, str]]] = {}
    for route in routes:
        identities = identities_by_name.setdefault(route.endpoint.__name__, set())
        for method in route.methods:
            identities.add((method, route.path))
    collisions = {
        name: sorted(identities)
        for name, identities in identities_by_name.items()
        if len(identities) > 1
    }
    assert collisions == {}, f"authorization endpoint-name collisions: {collisions}"

    classifications = {
        route.endpoint.__name__: route_authorization_class(route.endpoint.__name__)
        for route in routes
    }
    assert None not in classifications.values()
    business = {
        name for name, classification in classifications.items()
        if classification == RouteAuthorizationClass.PERMISSION_REQUIRED
    }
    assert business == set(ENDPOINT_PERMISSIONS)
    assert len(business) > 100
    assert sum(value == RouteAuthorizationClass.PUBLIC for value in classifications.values()) == 5
    assert sum(value == RouteAuthorizationClass.AUTHENTICATED for value in classifications.values()) == 2
    assert sum(value == RouteAuthorizationClass.ADMIN_ONLY for value in classifications.values()) == 6


@pytest.mark.parametrize("target", ["READY", "SUBMITTED"])
def test_case_worker_cannot_cross_final_workflow_boundary(target):
    user = SimpleNamespace(role="CASE_WORKER", is_active=True)
    with pytest.raises(HTTPException) as error:
        enforce_workflow_target(user, target)
    assert error.value.status_code == 403


@pytest.mark.parametrize("current,target", [("REVIEW", "PREPARE"), ("READY", "REVIEW")])
def test_case_worker_cannot_control_review_return_transitions(current, target):
    user = SimpleNamespace(role="CASE_WORKER", is_active=True)
    with pytest.raises(HTTPException) as error:
        enforce_workflow_target(user, target, current_state=current)
    assert error.value.status_code == 403


@pytest.mark.parametrize("role", ["REVIEWER", "ADMIN"])
def test_reviewer_and_admin_can_cross_final_workflow_boundary(role):
    user = SimpleNamespace(role=role, is_active=True)
    enforce_workflow_target(user, "READY")
    enforce_workflow_target(user, "SUBMITTED")


def test_admin_user_management_last_admin_and_audit(client, session):
    admin = enroll(client, session, "admin@example.com", "ADMIN")
    headers = auth_headers(client)
    assert client.get("/auth/users").status_code == 200
    assert client.patch(
        f"/auth/users/{admin.id}", headers=headers, json={"is_active": False}
    ).status_code == 409
    assert client.patch(
        f"/auth/users/{admin.id}", headers=headers, json={"role": "REVIEWER"}
    ).status_code == 409

    created = client.post("/auth/users", headers=headers, json={
        "email": "worker@example.com", "display_name": "Worker", "password": PASSWORD,
        "role": "CASE_WORKER",
    })
    assert created.status_code == 201
    worker_id = created.json()["id"]
    updated = client.patch(
        f"/auth/users/{worker_id}", headers=headers, json={"role": "REVIEWER"}
    )
    assert updated.status_code == 200 and updated.json()["role"] == "REVIEWER"
    reset = client.post(f"/auth/users/{worker_id}/mfa/reset", headers=headers)
    assert reset.status_code == 200
    events = client.get("/auth/audit-events").json()
    assert {item["action"] for item in events} >= {"USER_CREATED", "USER_ROLE_CHANGED", "MFA_RESET"}
    serialized = str(events).casefold()
    for forbidden in ("password_hash", "mfa_secret", "csrf_token", "challenge_token"):
        assert forbidden not in serialized


def test_non_admin_cannot_use_user_or_security_admin(client, session):
    enroll(client, session, "reviewer@example.com", "REVIEWER")
    assert client.get("/auth/users").status_code == 403
    assert client.get("/auth/audit-events").status_code == 403


def test_deactivation_revocation_and_mfa_reset_are_transactional(client, session):
    enroll(client, session, "admin@example.com", "ADMIN")
    target = create_user(
        session, email="target@example.com", display_name="Target", password=PASSWORD, role="CASE_WORKER"
    )
    target.mfa_enabled = True
    target.mfa_secret_encrypted = "encrypted-placeholder"
    target.sessions.append(AuthSession(
        token_hash="a" * 64, csrf_token_hash="b" * 64,
        expires_at=now_utc() + timedelta(hours=1),
    ))
    target.challenges.append(MfaChallenge(
        token_hash="c" * 64, purpose="login", expires_at=now_utc() + timedelta(minutes=5),
    ))
    session.commit()
    revoked = client.post(
        f"/auth/users/{target.id}/sessions/revoke", headers=auth_headers(client)
    )
    assert revoked.status_code == 200 and revoked.json()["revoked_sessions"] == 1
    session.refresh(target)
    assert target.sessions[0].revoked_at is not None
    assert target.challenges[0].consumed_at is None
    target.sessions.append(AuthSession(
        token_hash="1" * 64, csrf_token_hash="2" * 64,
        expires_at=now_utc() + timedelta(hours=1),
    ))
    session.commit()
    response = client.post(f"/auth/users/{target.id}/mfa/reset", headers=auth_headers(client))
    assert response.status_code == 200 and response.json()["revoked_sessions"] == 1
    session.refresh(target)
    assert not target.mfa_enabled and target.mfa_secret_encrypted is None
    assert target.sessions[0].revoked_at is not None and target.challenges[0].consumed_at is not None
    login = client.post("/auth/login", json={"email": target.email, "password": PASSWORD})
    assert login.status_code == 200 and login.json()["status"] == "mfa_enrollment_required"

    target.sessions.append(AuthSession(
        token_hash="d" * 64, csrf_token_hash="e" * 64,
        expires_at=now_utc() + timedelta(hours=1),
    ))
    target.challenges.append(MfaChallenge(
        token_hash="f" * 64, purpose="login", expires_at=now_utc() + timedelta(minutes=5),
    ))
    session.commit()
    deactivated = client.patch(
        f"/auth/users/{target.id}", headers=auth_headers(client), json={"is_active": False}
    )
    assert deactivated.status_code == 200
    session.refresh(target)
    assert not target.is_active
    assert all(item.revoked_at is not None for item in target.sessions)
    assert all(item.consumed_at is not None for item in target.challenges)
    actions = set(session.scalars(select(ApplicationAuditEvent.action)))
    assert {"SESSIONS_REVOKED", "MFA_RESET", "USER_DEACTIVATED"} <= actions


def test_case_audit_visibility_and_append_only_guard(client, session):
    enroll(client, session, "reviewer@example.com", "REVIEWER")
    created = client.post("/cases", headers=auth_headers(client), json={
        "case_number": "AUDIT-1", "visa_type": "TRV", "purpose": "visit",
    })
    assert created.status_code == 201
    case_id = created.json()["id"]
    timeline = client.get(f"/cases/{case_id}/audit-events")
    assert timeline.status_code == 200
    assert timeline.json()[0]["action"] == "CASE_CREATED"

    row = session.scalar(select(ApplicationAuditEvent))
    row.action = "TAMPERED"
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()
    session.rollback()


def test_sensitive_metadata_is_rejected(session):
    with pytest.raises(ValueError, match="sensitive"):
        record_audit(
            session, actor=None, action="TEST", target_entity_type="TEST",
            metadata={"nested": {"password": "never-store-this"}},
        )


def test_failed_audit_insert_rolls_back_critical_fact_mutation(client, session):
    enroll(client, session, "atomic-admin@example.com", "ADMIN")
    case_response = client.post("/cases", headers=auth_headers(client), json={
        "case_number": "ATOMIC-1", "visa_type": "TRV", "purpose": "visit",
    })
    assert case_response.status_code == 201
    case_id = case_response.json()["id"]

    def fail_audit_insert(_mapper, _connection, _target):
        raise IntegrityError("forced audit failure", {}, RuntimeError("forced"))

    event.listen(ApplicationAuditEvent, "before_insert", fail_audit_insert)
    try:
        response = client.post(
            f"/cases/{case_id}/facts",
            headers=auth_headers(client),
            json={
                "key": "atomic.probe", "value_json": True,
                "source_type": "manual", "source_reference": "atomicity-test",
                "status": "confirmed",
            },
        )
    finally:
        event.remove(ApplicationAuditEvent, "before_insert", fail_audit_insert)

    assert response.status_code == 409
    assert session.scalar(select(func.count()).select_from(models.Fact)) == 0
    assert session.scalar(select(func.count()).select_from(ApplicationAuditEvent).where(
        ApplicationAuditEvent.action == "FACT_CREATED"
    )) == 0


def test_migration_upgrades_0010_to_single_new_head(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'm10b-upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name != "application_audit_events":
                table.create(connection)
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0010_auth_foundation')"))
    config = Config(str(PROJECT_ROOT / "backend/alembic.ini"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_authorization_audit"
    assert "application_audit_events" in inspect(engine).get_table_names()
    engine.dispose()
