from __future__ import annotations

import base64
import hashlib
from datetime import timedelta

import pytest
from argon2.low_level import Type
from cryptography.fernet import Fernet
from alembic import command
from alembic.config import Config
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from backend.app.auth import (
    PASSWORD_HASHER,
    SESSION_COOKIE_NAME,
    create_user,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    now_utc,
    require_authenticated_request,
    totp_code,
    verify_totp,
    verify_password,
)
from backend.app.database import get_session
from backend.app.main import app
from backend.app.models.auth import AuthSession, LoginThrottle, MfaChallenge, User
from backend.scripts import create_admin
from backend.app.deployment_preflight import PROJECT_ROOT


pytestmark = pytest.mark.real_auth
PASSWORD = "ValidPassword123"


def test_auth_cryptographic_implementations_remain_production_grade():
    assert PASSWORD_HASHER.type is Type.ID
    assert Fernet.generate_key()
    encrypted = encrypt_secret("JBSWY3DPEHPK3PXP")
    assert decrypt_secret(encrypted) == "JBSWY3DPEHPK3PXP"
    code = totp_code("JBSWY3DPEHPK3PXP", at_time=1_700_000_000)
    assert verify_totp("JBSWY3DPEHPK3PXP", code, at_time=1_700_000_000)


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch):
    key = base64.urlsafe_b64encode(b"m10a-test-encryption-key-0000000").decode()
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", key)
    monkeypatch.setenv("AUTH_SESSION_HOURS", "12")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")


@pytest.fixture
def client(session):
    def override_session():
        yield session
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()


def add_user(session, email="admin@example.com", role="ADMIN", active=True):
    user = create_user(session, email=email, display_name="Test Employee", password=PASSWORD, role=role)
    user.is_active = active
    session.commit()
    return user


def enroll(client, session, *, role="ADMIN", email="admin@example.com"):
    user = add_user(session, role=role, email=email)
    login = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200
    body = login.json()
    assert body["status"] == "mfa_enrollment_required"
    verified = client.post("/auth/mfa/verify", json={
        "challenge_token": body["challenge_token"],
        "code": totp_code(body["enrollment_secret"]),
    })
    assert verified.status_code == 200
    return user, body, verified


def csrf(client: TestClient) -> str:
    return client.cookies.get("va_csrf")


def test_user_normalization_password_hash_and_inactive_denial(client, session):
    user = add_user(session, email=" Employee@Example.COM ")
    assert user.email == "employee@example.com"
    assert user.password_hash != PASSWORD and user.password_hash.startswith("$argon2id$")
    assert verify_password(user.password_hash, PASSWORD)
    with pytest.raises(ValueError, match="already exists"):
        create_user(session, email="EMPLOYEE@example.com", display_name="Duplicate", password=PASSWORD, role="REVIEWER")
    user.is_active = False; session.commit()
    response = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 401


def test_password_login_is_enumeration_safe_and_throttled(client, session):
    add_user(session)
    wrong = client.post("/auth/login", json={"email": "admin@example.com", "password": "WrongPassword123"})
    unknown = client.post("/auth/login", json={"email": "missing@example.com", "password": "WrongPassword123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    for _ in range(4):
        client.post("/auth/login", json={"email": "admin@example.com", "password": "WrongPassword123"})
    blocked = client.post("/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert session.scalar(select(LoginThrottle).where(LoginThrottle.failed_attempts >= 5)) is not None


def test_mfa_enrollment_session_hash_cookie_and_subsequent_login(client, session, monkeypatch):
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    user = add_user(session)
    login = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    body = login.json()
    invalid = client.post("/auth/mfa/verify", json={"challenge_token": body["challenge_token"], "code": "000000"})
    assert invalid.status_code == 401
    completed = client.post("/auth/mfa/verify", json={"challenge_token": body["challenge_token"], "code": totp_code(body["enrollment_secret"])})
    assert completed.status_code == 200
    session.refresh(user)
    assert user.mfa_enabled and user.mfa_secret_encrypted and body["enrollment_secret"] not in user.mfa_secret_encrypted
    header = completed.headers.get("set-cookie", "")
    assert "HttpOnly" in header and "Secure" in header and "SameSite=strict" in header and "Path=/" in header
    raw_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    stored = session.scalar(select(AuthSession))
    assert stored.token_hash == hashlib.sha256(raw_cookie.encode()).hexdigest()
    assert raw_cookie not in stored.token_hash
    client.cookies.clear()
    second = client.post("/auth/login", json={"email": user.email, "password": PASSWORD}).json()
    assert second["status"] == "mfa_required"
    assert second["enrollment_secret"] is None


def test_expired_and_reused_mfa_challenges_are_denied(client, session):
    user = add_user(session)
    first = client.post("/auth/login", json={"email": user.email, "password": PASSWORD}).json()
    challenge = session.scalar(select(MfaChallenge).where(MfaChallenge.token_hash == hashlib.sha256(first["challenge_token"].encode()).hexdigest()))
    challenge.expires_at = now_utc() - timedelta(seconds=1); session.commit()
    assert client.post("/auth/mfa/verify", json={"challenge_token": first["challenge_token"], "code": totp_code(first["enrollment_secret"])}).status_code == 401
    second = client.post("/auth/login", json={"email": user.email, "password": PASSWORD}).json()
    payload = {"challenge_token": second["challenge_token"], "code": totp_code(second["enrollment_secret"])}
    assert client.post("/auth/mfa/verify", json=payload).status_code == 200
    assert client.post("/auth/mfa/verify", json=payload).status_code == 401


def test_session_validation_csrf_logout_and_inactive_user(client, session):
    user, _, _ = enroll(client, session)
    assert client.get("/auth/me").status_code == 200
    assert client.get("/cases").status_code == 200
    assert client.post("/cases", json={"case_number": "AUTH-1", "visa_type": "TRV", "purpose": "test"}).status_code == 403
    valid = client.post("/cases", headers={"X-CSRF-Token": csrf(client)}, json={"case_number": "AUTH-1", "visa_type": "TRV", "purpose": "test"})
    assert valid.status_code == 201
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf(client)}).status_code == 204
    stored = session.scalar(select(AuthSession)); session.refresh(stored)
    assert stored.revoked_at is not None
    assert client.get("/cases").status_code == 401

    client.cookies.clear(); user2, _, _ = enroll(client, session, email="inactive@example.com")
    user2.is_active = False; session.commit()
    assert client.get("/cases").status_code == 401


@pytest.mark.parametrize("state", ["invalid", "expired", "revoked"])
def test_invalid_expired_and_revoked_sessions_fail(client, session, state):
    enroll(client, session)
    stored = session.scalar(select(AuthSession))
    if state == "invalid":
        client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-session")
    elif state == "expired":
        stored.expires_at = now_utc() - timedelta(seconds=1); session.commit()
    else:
        stored.revoked_at = now_utc(); session.commit()
    assert client.get("/cases").status_code == 401


@pytest.mark.parametrize("role", ["ADMIN", "CASE_WORKER", "REVIEWER"])
def test_all_roles_access_business_but_only_admin_creates_users(client, session, role):
    enroll(client, session, role=role)
    assert client.get("/cases").status_code == 200
    response = client.post("/auth/users", headers={"X-CSRF-Token": csrf(client)}, json={
        "email": f"new-{role.lower()}@example.com", "display_name": "New User", "password": PASSWORD, "role": "REVIEWER",
    })
    assert response.status_code == (201 if role == "ADMIN" else 403)


def test_business_routes_fail_closed_and_health_is_public(client):
    public = {"/health", "/health/live", "/health/ready", "/auth/login", "/auth/mfa/verify"}

    effective_routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            effective_routes.append(route)
        elif hasattr(route, "effective_route_contexts"):
            effective_routes.extend(route.effective_route_contexts())

    def dependency_calls(dependant):
        calls = {item.call for item in dependant.dependencies}
        for item in dependant.dependencies:
            calls.update(dependency_calls(item))
        return calls

    assert len(effective_routes) > 100
    for route in effective_routes:
        if route.path.startswith("/auth/") or route.path in public:
            continue
        assert require_authenticated_request in dependency_calls(route.dependant), route.path
    assert client.get("/cases").status_code == 401
    assert client.get("/cases/00000000-0000-0000-0000-000000000001").status_code == 401
    assert client.get("/documents/00000000-0000-0000-0000-000000000001").status_code == 401
    assert client.get("/documents/00000000-0000-0000-0000-000000000001/content").status_code == 401
    assert client.get("/preparation-artifacts/00000000-0000-0000-0000-000000000001/content").status_code == 401
    assert client.post("/cases", json={}).status_code == 401
    assert client.post("/cases/00000000-0000-0000-0000-000000000001/prepare", json={}).status_code == 401
    assert client.get("/health/live").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_admin_bootstrap_is_interactive_duplicate_safe_and_does_not_print_secrets(session, monkeypatch, capsys):
    monkeypatch.setattr(create_admin, "engine", session.get_bind())
    answers = iter([PASSWORD, PASSWORD, PASSWORD, PASSWORD])
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda _prompt: next(answers))
    args = ["--email", "first-admin@example.com", "--display-name", "First Admin"]
    assert create_admin.main(args) == 0
    assert create_admin.main(args) == 2
    output = capsys.readouterr().out
    assert PASSWORD not in output and "$argon2" not in output and "postgresql" not in output


def test_auth_migration_upgrades_an_existing_0009_database(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'existing-0009.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0009_canada_preparation_runs')"))
        connection.execute(text(
            "CREATE TABLE canada_import_candidates "
            "(id VARCHAR(32) PRIMARY KEY, proposed_value_json JSON NOT NULL)"
        ))
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(PROJECT_ROOT / "backend/alembic.ini"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015_intake_failure_detail"
    assert {"auth_users", "auth_sessions", "auth_mfa_challenges"} <= set(inspect(engine).get_table_names())
    engine.dispose()
