from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from .runtime_dependencies import check_auth_runtime_dependencies


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "deployment" / "environment-contract.json"
EXPECTED_ALEMBIC_HEAD = "0010_auth_foundation"
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "example-password")
MFA_KEY_PLACEHOLDER = "cmVwbGFjZS13aXRoLWdlbmVyYXRlZC1rZXktMDAwMDA="


def _result(name: str, ok: bool, code: str) -> dict[str, str]:
    return {"name": name, "status": "PASS" if ok else "FAIL", "code": code}


def _positive_megabytes(value: str | None, default: str) -> bool:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return False
    return 1 <= parsed <= 1024


def _database_url_valid(raw: str | None, *, allow_placeholders: bool) -> bool:
    if not raw:
        return False
    try:
        value = make_url(raw)
    except Exception:
        return False
    if value.drivername != "postgresql+psycopg":
        return False
    if not all((value.username, value.password, value.host, value.database)):
        return False
    return allow_placeholders or not any(marker in raw.casefold() for marker in PLACEHOLDER_MARKERS)


def _origins_valid(raw: str | None) -> bool:
    if not raw or "*" in raw:
        return False
    for origin in raw.split(","):
        parsed = urlsplit(origin.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return False
    return True


def _authentication_valid(environment: Mapping[str, str], *, allow_placeholders: bool) -> bool:
    key = environment.get("MFA_ENCRYPTION_KEY", "")
    try:
        decoded_key = base64.b64decode(key.encode("ascii"), altchars=b"-_", validate=True)
        hours = int(environment.get("AUTH_SESSION_HOURS", "12"))
    except (ValueError, TypeError, UnicodeError):
        return False
    if len(decoded_key) != 32 or not 1 <= hours <= 168:
        return False
    if environment.get("AUTH_COOKIE_SECURE", "true").casefold() not in {"true", "false", "1", "0", "yes", "no"}:
        return False
    return allow_placeholders or key != MFA_KEY_PLACEHOLDER


def _authentication_dependency_check() -> tuple[bool, str]:
    ok, code, _details = check_auth_runtime_dependencies()
    return ok, code


def _storage_roots(
    environment: Mapping[str, str], *, check_writable: bool
) -> tuple[bool, str]:
    values = [
        environment.get("DOCUMENT_STORAGE_ROOT", ""),
        environment.get("GENERATED_ARTIFACT_STORAGE_ROOT", ""),
    ]
    if not all(values):
        return False, "storage_root_missing"
    roots = [Path(value).expanduser() for value in values]
    if not all(root.is_absolute() for root in roots):
        return False, "storage_root_not_absolute"
    resolved = [root.resolve(strict=False) for root in roots]
    if resolved[0] == resolved[1]:
        return False, "storage_roots_not_separate"
    if any(root == PROJECT_ROOT or PROJECT_ROOT in root.parents for root in resolved):
        return False, "persistent_storage_inside_repository"
    if check_writable:
        for root in resolved:
            if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK | os.X_OK):
                return False, "storage_root_not_writable"
    return True, "storage_roots_valid"


def _template_check() -> tuple[bool, str]:
    try:
        matrix = json.loads(
            (PROJECT_ROOT / "canada" / "coverage_matrix.yaml").read_text(encoding="utf-8")
        )
        templates = matrix["templates"]
        if set(templates) != {"IMM5257", "IMM5707", "IMM5476"}:
            return False, "template_manifest_invalid"
        for metadata in templates.values():
            source = PROJECT_ROOT / metadata["file"]
            if not source.is_file():
                return False, "template_missing"
            if hashlib.sha256(source.read_bytes()).hexdigest() != metadata["sha256"]:
                return False, "template_hash_mismatch"
    except Exception:
        return False, "template_manifest_unreadable"
    return True, "templates_valid"


def _migration_check() -> tuple[bool, str]:
    try:
        config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception:
        return False, "migration_metadata_unavailable"
    return (
        (True, "alembic_head_valid")
        if heads == [EXPECTED_ALEMBIC_HEAD]
        else (False, "alembic_head_mismatch")
    )


def _dependency_check() -> tuple[bool, str]:
    try:
        import pymupdf  # noqa: F401
        import reportlab  # noqa: F401
    except Exception:
        return False, "generator_dependency_unavailable"
    return True, "generator_dependencies_available"


def _deployment_env_check(
    environment: Mapping[str, str], *, allow_placeholders: bool
) -> tuple[bool, str]:
    try:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False, "environment_contract_unreadable"
    required = {
        item["name"]
        for item in contract["variables"]
        if item["required"] and item["env_file"]
    }
    if any(not environment.get(name, "").strip() for name in required):
        return False, "required_environment_missing"
    data_root = Path(environment["DATA_ROOT"]).expanduser()
    if not data_root.is_absolute() or str(data_root) in {"/", "/home", "/srv"}:
        return False, "data_root_unsafe"
    for name in ("POSTGRES_DB", "POSTGRES_USER"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", environment[name]):
            return False, "postgres_identifier_invalid"
    password = environment["POSTGRES_PASSWORD"]
    if not allow_placeholders and any(
        marker in password.casefold() for marker in PLACEHOLDER_MARKERS
    ):
        return False, "postgres_password_placeholder"
    try:
        port = int(environment.get("APP_PORT", "8080"))
    except ValueError:
        return False, "app_port_invalid"
    if not 1 <= port <= 65535:
        return False, "app_port_invalid"
    return True, "environment_contract_valid"


def validate_deployment_configuration(
    environment: Mapping[str, str] | None = None,
    *,
    check_writable: bool = False,
    allow_placeholders: bool = False,
) -> dict[str, object]:
    env = dict(os.environ if environment is None else environment)
    checks: list[dict[str, str]] = []

    if "DATA_ROOT" in env:
        contract_ok, contract_code = _deployment_env_check(
            env, allow_placeholders=allow_placeholders
        )
        checks.append(_result("environment_contract", contract_ok, contract_code))

    database_ok = _database_url_valid(
        env.get("DATABASE_URL"), allow_placeholders=allow_placeholders
    )
    checks.append(_result("database_url", database_ok, "database_url_valid" if database_ok else "database_url_invalid"))

    storage_ok, storage_code = _storage_roots(env, check_writable=check_writable)
    checks.append(_result("storage_roots", storage_ok, storage_code))

    for name, default in (
        ("MAX_UPLOAD_SIZE_MB", "20"),
        ("MAX_GENERATED_ARTIFACT_MB", "30"),
        ("MAX_CONVERSATION_IMPORT_MB", "2"),
    ):
        ok = _positive_megabytes(env.get(name), default)
        checks.append(_result(name.casefold(), ok, "limit_valid" if ok else "limit_invalid"))

    origins_ok = _origins_valid(env.get("CORS_ORIGINS"))
    checks.append(_result("cors_origins", origins_ok, "cors_origins_valid" if origins_ok else "cors_origins_invalid"))

    auth_ok = _authentication_valid(env, allow_placeholders=allow_placeholders)
    checks.append(_result("authentication", auth_ok, "authentication_valid" if auth_ok else "authentication_invalid"))

    ai_provider = env.get("AI_PROVIDER", "").strip().casefold()
    ai_ok = ai_provider in {"", "disabled", "local_text", "local-text"}
    ai_ok = ai_ok and not env.get("AI_API_KEY", "").strip()
    ai_ok = ai_ok and (not env.get("AI_MODEL", "").strip() or ai_provider in {"local_text", "local-text"})
    checks.append(_result("classification_provider", ai_ok, "provider_valid" if ai_ok else "provider_invalid"))

    quality_ok = env.get("QUALITY_PROVIDER", "manual_only").strip().casefold() in {
        "", "disabled", "manual_only", "manual-only"
    }
    checks.append(_result("quality_provider", quality_ok, "provider_valid" if quality_ok else "provider_invalid"))

    fact_ok = env.get("FACT_EXTRACTION_PROVIDER", "disabled").strip().casefold() in {
        "", "disabled", "local_rules", "local-rules"
    }
    checks.append(_result("fact_extraction_provider", fact_ok, "provider_valid" if fact_ok else "provider_invalid"))

    for name, check in (
        ("authentication_dependencies", _authentication_dependency_check),
        ("templates", _template_check),
        ("alembic_metadata", _migration_check),
        ("generator_dependencies", _dependency_check),
    ):
        ok, code = check()
        checks.append(_result(name, ok, code))

    ready = all(check["status"] == "PASS" for check in checks)
    return {
        "status": "PASS" if ready else "FAIL",
        "expected_alembic_head": EXPECTED_ALEMBIC_HEAD,
        "checks": checks,
    }


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid_env_line_{line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise ValueError(f"invalid_env_name_{line_number}")
        values[name] = value.strip()
    return values


def environment_from_deployment_file(path: Path) -> dict[str, str]:
    values = parse_env_file(path)
    data_root = Path(values.get("DATA_ROOT", ""))
    if data_root.is_absolute():
        values.setdefault("DOCUMENT_STORAGE_ROOT", str(data_root / "document-storage"))
        values.setdefault(
            "GENERATED_ARTIFACT_STORAGE_ROOT",
            str(data_root / "generated-artifact-storage"),
        )
    return values
