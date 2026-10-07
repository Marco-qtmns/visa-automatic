from __future__ import annotations

import ast
import importlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app import deployment_preflight as preflight_module
from backend.app.deployment_preflight import (
    PROJECT_ROOT,
    environment_from_deployment_file,
    validate_deployment_configuration,
)
from backend.app.runtime_dependencies import (
    AUTH_RUNTIME_REQUIREMENTS,
    check_auth_runtime_dependencies,
)
from backend.scripts import runtime_import_smoke
from backend.scripts import (
    synthetic_staging_case,
    verify_restored_staging,
    verify_synthetic_staging,
)
from deployment.backup_manifest import create_manifest, restore_storage, verify_manifest
from deployment.d1_acceptance import acceptance
from deployment.d1_report import initial_report, update_report
from deployment.synthetic_smoke_contract import (
    EXPECTED_ARTIFACT_TYPES,
    parse_producer_output,
)


def _environment_names(path: Path) -> set[str]:
    return {
        line.split("=", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def test_environment_contract_matches_example_and_preflight():
    contract = json.loads((PROJECT_ROOT / "deployment/environment-contract.json").read_text())
    assert contract["expected_alembic_head"] == "0011_authorization_audit"
    variables = contract["variables"]
    assert len({item["name"] for item in variables}) == len(variables)
    for item in variables:
        assert set(item) == {
            "name", "service", "required", "env_file", "safe_example",
            "default", "secret", "validation", "missing_behavior",
        }
    expected = {item["name"] for item in variables if item["env_file"]}
    assert _environment_names(PROJECT_ROOT / ".env.production.example") == expected
    environment = environment_from_deployment_file(PROJECT_ROOT / ".env.production.example")
    result = validate_deployment_configuration(environment, allow_placeholders=True)
    assert result["status"] == "PASS"


def test_environment_contract_covers_application_and_compose_reads():
    contract = json.loads((PROJECT_ROOT / "deployment/environment-contract.json").read_text())
    documented = {item["name"] for item in contract["variables"]}
    sources = [
        *sorted((PROJECT_ROOT / "backend/app").rglob("*.py")),
        *sorted((PROJECT_ROOT / "frontend/src").rglob("*.ts")),
        *sorted((PROJECT_ROOT / "frontend/src").rglob("*.tsx")),
        PROJECT_ROOT / "compose.yaml",
    ]
    used: set[str] = set()
    for source in sources:
        text = source.read_text(encoding="utf-8")
        used.update(re.findall(r'os\.environ\.get\("([A-Z][A-Z0-9_]*)"', text))
        used.update(re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)", text))
        if source.name == "compose.yaml":
            used.update(re.findall(r"\$\{([A-Z][A-Z0-9_]*)[:}]", text))
    assert used <= documented


def test_preflight_rejects_unsafe_configuration_without_echoing_secret(tmp_path):
    environment = environment_from_deployment_file(PROJECT_ROOT / ".env.production.example")
    environment["DATA_ROOT"] = "/"
    environment["DOCUMENT_STORAGE_ROOT"] = str(tmp_path / "same")
    environment["GENERATED_ARTIFACT_STORAGE_ROOT"] = str(tmp_path / "same")
    environment["DATABASE_URL"] = "postgresql+psycopg://user:do-not-print@postgres/db"
    environment["AI_API_KEY"] = "do-not-print"
    result = validate_deployment_configuration(environment)
    rendered = json.dumps(result)
    assert result["status"] == "FAIL"
    assert "do-not-print" not in rendered
    codes = {item["code"] for item in result["checks"]}
    assert "data_root_unsafe" in codes
    assert "storage_roots_not_separate" in codes
    assert "provider_invalid" in codes


def test_preflight_can_check_real_separate_writable_roots(tmp_path):
    environment = environment_from_deployment_file(PROJECT_ROOT / ".env.production.example")
    environment.update({
        "DATA_ROOT": str(tmp_path),
        "POSTGRES_PASSWORD": "synthetic-test-password-only",
        "DATABASE_URL": "postgresql+psycopg://synthetic:synthetic-test-password-only@postgres/synthetic",
        "MFA_ENCRYPTION_KEY": "bTEwYS10ZXN0LWVuY3J5cHRpb24ta2V5LTAwMDAwMDA=",
        "DOCUMENT_STORAGE_ROOT": str(tmp_path / "documents"),
        "GENERATED_ARTIFACT_STORAGE_ROOT": str(tmp_path / "generated"),
    })
    (tmp_path / "documents").mkdir()
    (tmp_path / "generated").mkdir()
    result = validate_deployment_configuration(environment, check_writable=True)
    assert result["status"] == "PASS"


def test_docker_context_and_one_origin_hygiene():
    root_ignore = (PROJECT_ROOT / ".dockerignore").read_text()
    for pattern in (
        ".git", ".env.*", ".venv", "__pycache__", ".pytest_cache",
        "backend/storage", "backend/generated-storage", "deployment/reports",
        "*.dump", "*.tar.gz", "**/*.pdf",
    ):
        assert pattern in root_ignore
    assert "!.env.production.example" not in root_ignore
    assert "!templates/canada/*.pdf" in root_ignore
    frontend_ignore = (PROJECT_ROOT / "frontend/.dockerignore").read_text()
    for pattern in ("node_modules", ".next", "coverage", ".env.*", ".cache", ".turbo"):
        assert pattern in frontend_ignore
    backend_dockerfile = (PROJECT_ROOT / "backend/Dockerfile").read_text()
    assert "COPY templates/canada /app/templates/canada" in backend_dockerfile
    assert "COPY deployment/environment-contract.json /app/deployment/environment-contract.json" in backend_dockerfile
    assert "slim-bookworm" in backend_dockerfile and "alpine" not in backend_dockerfile
    frontend_source = (PROJECT_ROOT / "frontend/src/lib/api/client.ts").read_text()
    assert '?? "/api"' in frontend_source
    assert "localhost:8000" not in frontend_source


def test_deployment_runtime_dependencies_are_pinned():
    requirements = [
        line.strip()
        for line in (PROJECT_ROOT / "requirements.deploy.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert requirements and all("==" in item for item in requirements)
    pinned_distributions = {item.split("==", 1)[0].casefold() for item in requirements}
    assert {item.distribution.casefold() for item in AUTH_RUNTIME_REQUIREMENTS} <= pinned_distributions
    package = json.loads((PROJECT_ROOT / "frontend/package.json").read_text())
    assert package["dependencies"] == {
        "next": "16.3.8", "react": "19.3.0", "react-dom": "19.3.0"
    }
    backend_image = (PROJECT_ROOT / "backend/Dockerfile").read_text()
    frontend_image = (PROJECT_ROOT / "frontend/Dockerfile").read_text()
    assert backend_image.startswith("FROM python:3.13.16-slim-bookworm")
    assert frontend_image.count("FROM node:22.23.3-bookworm-slim") == 3
    assert backend_image.count("pip install --requirement /app/requirements.deploy.txt") == 1
    assert "python -m backend.scripts.runtime_import_smoke" in backend_image
    assert all(item.distribution not in backend_image for item in AUTH_RUNTIME_REQUIREMENTS)


def test_auth_runtime_smoke_uses_real_argon2_fernet_and_stdlib_totp(capsys):
    assert check_auth_runtime_dependencies() == (
        True,
        "auth_runtime_dependencies_available",
        (),
    )
    assert runtime_import_smoke.main() == 0
    assert capsys.readouterr().out.strip() == "PASS auth_runtime_dependencies_available"


def test_missing_auth_dependency_has_stable_preflight_failure(monkeypatch):
    def missing_cryptography(name: str):
        if name == "cryptography.fernet":
            raise ModuleNotFoundError("synthetic missing dependency")
        return importlib.import_module(name)

    ok, code, details = check_auth_runtime_dependencies(importer=missing_cryptography)
    assert not ok
    assert code == "auth_runtime_dependency_missing"
    assert details == ("cryptography",)

    monkeypatch.setattr(
        preflight_module,
        "check_auth_runtime_dependencies",
        lambda: (False, "auth_runtime_dependency_missing", ("cryptography",)),
    )
    environment = environment_from_deployment_file(PROJECT_ROOT / ".env.production.example")
    result = validate_deployment_configuration(environment, allow_placeholders=True)
    auth_check = next(item for item in result["checks"] if item["name"] == "authentication_dependencies")
    assert result["status"] == "FAIL"
    assert auth_check == {
        "name": "authentication_dependencies",
        "status": "FAIL",
        "code": "auth_runtime_dependency_missing",
    }
    assert "ModuleNotFoundError" not in json.dumps(result)


def test_backend_runtime_identity_and_restore_normalization_contract():
    contract_path = PROJECT_ROOT / "deployment/backend-runtime-identity.env"
    contract = {
        name: value
        for name, value in (
            line.split("=", 1)
            for line in contract_path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
    }
    assert set(contract) == {"BACKEND_RUNTIME_UID", "BACKEND_RUNTIME_GID"}
    assert all(re.fullmatch(r"[1-9][0-9]*", value) for value in contract.values())

    dockerfile = (PROJECT_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "COPY deployment/backend-runtime-identity.env" in dockerfile
    assert ". /tmp/backend-runtime-identity.env" in dockerfile
    assert 'groupadd --gid "$BACKEND_RUNTIME_GID"' in dockerfile
    assert 'useradd --uid "$BACKEND_RUNTIME_UID"' in dockerfile
    assert "USER visaautomatic" in dockerfile
    assert contract["BACKEND_RUNTIME_UID"] not in dockerfile
    assert contract["BACKEND_RUNTIME_GID"] not in dockerfile

    scripts = {
        name: (PROJECT_ROOT / "deployment" / name).read_text(encoding="utf-8")
        for name in ("prepare-host.sh", "raspberry-preflight.sh", "restore-test.sh")
    }
    for source in scripts.values():
        assert '. "$script_dir/backend-runtime-identity.env"' in source
        assert contract["BACKEND_RUNTIME_UID"] not in source
        assert contract["BACKEND_RUNTIME_GID"] not in source

    restore = scripts["restore-test.sh"]
    assert "backend_identity=$(docker run --rm --entrypoint sh" in restore
    assert '"$backend_identity" != "$BACKEND_RUNTIME_UID:$BACKEND_RUNTIME_GID"' in restore
    privileged = restore.split("docker run --rm --user 0:0", 1)[1].split(
        "configured_url=", 1
    )[0]
    assert privileged.count('-v "') == 2
    assert "compose run" not in privileged
    assert "data_root" not in privileged.casefold()
    assert "sudo" not in privileged
    assert 'chown -R "$runtime_uid:$runtime_gid"' in privileged
    assert "find \"$root\" -type d -exec chmod 0700" in privileged
    assert "find \"$root\" -type f -exec chmod 0600" in privileged
    assert "chmod 0777" not in restore and "chmod 777" not in restore

    verifier = restore.split("compose run --rm --no-deps --entrypoint sh", 1)[1]
    assert "--user" not in verifier
    assert "actual_identity=$(id -u):$(id -g)" in verifier
    assert "verify_restored_staging" in verifier


def test_backend_image_is_resolved_from_compose_after_build():
    compose_source = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "    image: visa-automatic-d1-backend:local" in compose_source

    preflight = (
        PROJECT_ROOT / "deployment/raspberry-preflight.sh"
    ).read_text(encoding="utf-8")
    build_index = preflight.index("compose build --pull backend frontend")
    resolution_index = preflight.index("backend_image=$(resolve_backend_image)")
    run_index = preflight.index(
        'docker run --rm --entrypoint sh "$backend_image"', resolution_index
    )
    assert "backend_image=" not in preflight[:build_index]
    assert build_index < resolution_index < run_index
    assert "compose images -q backend" not in preflight
    assert 'docker image inspect --format \'{{.Id}}\' "$image_name"' in preflight
    assert (
        '|| critical "Current backend image could not be resolved after build"'
        in preflight
    )
    assert "Backend image runtime identity matches the deployment contract" in preflight

    restore = (PROJECT_ROOT / "deployment/restore-test.sh").read_text(encoding="utf-8")
    assert "compose images -q backend" not in restore
    assert 'docker image inspect --format \'{{.Id}}\' "$image_name"' in restore
    restore_resolution = restore.index("backend_image=$(resolve_backend_image)")
    restore_run = restore.index(
        'docker run --rm --entrypoint sh "$backend_image"', restore_resolution
    )
    assert restore_resolution < restore_run
    assert "Current backend image could not be resolved from the Compose service" in restore
    assert '"$backend_identity" != "$BACKEND_RUNTIME_UID:$BACKEND_RUNTIME_GID"' in restore


def test_accepted_migration_chain_has_one_expected_head():
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "backend/alembic.ini")))
    assert script.get_heads() == ["0011_authorization_audit"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert [item.revision for item in revisions] == [
        "0011_authorization_audit",
        "0010_auth_foundation",
        "0009_canada_preparation_runs",
        "0008_canada_legacy_import",
        "0007_canada_application_model",
        "0006_whatsapp_fact_extraction",
        "0005_doc_quality_completeness",
        "0004_document_classification",
        "0003_document_matching",
        "0002_workflow_state_machine",
        "0001_core_data_model",
    ]


def test_migration_revision_graph_fits_alembic_version_column():
    """Guard the VARCHAR(32) Alembic version table used by this project."""
    revisions: dict[str, str | None] = {}
    for path in sorted((PROJECT_ROOT / "backend/migrations/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        metadata: dict[str, str | None] = {}
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    metadata[target.id] = ast.literal_eval(node.value)

        revision = metadata.get("revision")
        assert isinstance(revision, str), f"{path.name} has no string revision"
        assert len(revision) <= 32, f"{path.name} revision exceeds VARCHAR(32)"
        assert revision not in revisions, f"duplicate revision: {revision}"
        revisions[revision] = metadata.get("down_revision")

    roots = [revision for revision, parent in revisions.items() if parent is None]
    assert len(roots) == 1, f"expected one migration root, found {roots}"
    for revision, parent in revisions.items():
        assert parent is None or parent in revisions, (
            f"revision {revision} references unknown down_revision {parent}"
        )

    children: dict[str, list[str]] = {revision: [] for revision in revisions}
    for revision, parent in revisions.items():
        if parent is not None:
            children[parent].append(revision)
    assert all(len(items) <= 1 for items in children.values()), "migration graph branches"
    heads = [revision for revision, items in children.items() if not items]
    assert heads == ["0011_authorization_audit"]

    visited: set[str] = set()
    current: str | None = roots[0]
    while current is not None:
        assert current not in visited, f"migration graph contains a cycle at {current}"
        visited.add(current)
        current = children[current][0] if children[current] else None
    assert visited == set(revisions), "migration graph is disconnected"


def test_deployment_files_have_no_mac_paths_and_storage_is_separate():
    paths = [
        PROJECT_ROOT / "compose.yaml",
        PROJECT_ROOT / "backend/Dockerfile",
        PROJECT_ROOT / "frontend/Dockerfile",
        PROJECT_ROOT / "deployment/Caddyfile",
        *sorted((PROJECT_ROOT / "deployment").glob("*.sh")),
    ]
    forbidden = "/" + "Users/"
    assert all(forbidden not in path.read_text(encoding="utf-8") for path in paths)
    compose = (PROJECT_ROOT / "compose.yaml").read_text()
    assert "${DATA_ROOT:?Set DATA_ROOT}/document-storage" in compose
    assert "${DATA_ROOT:?Set DATA_ROOT}/generated-artifact-storage" in compose
    assert "DOCUMENT_STORAGE_ROOT: /srv/visa-automatic/document-storage" in compose
    assert "GENERATED_ARTIFACT_STORAGE_ROOT: /srv/visa-automatic/generated-artifact-storage" in compose
    postgres_block, backend_block = compose.split("  backend:", 1)
    assert "ports:" not in postgres_block
    frontend_block = backend_block.split("  frontend:", 1)[0]
    assert "ports:" not in frontend_block
    frontend_only = backend_block.split("  frontend:", 1)[1].split("  proxy:", 1)[0]
    assert "ports:" not in frontend_only
    proxy_only = compose.split("  proxy:", 1)[1]
    assert '"${BIND_ADDRESS:-127.0.0.1}:${APP_PORT:-8080}:8080"' in proxy_only
    caddy = (PROJECT_ROOT / "deployment/Caddyfile").read_text()
    assert "@api path /api/*" in caddy
    assert "uri strip_prefix /api" in caddy
    assert "reverse_proxy backend:8000" in caddy
    assert "reverse_proxy frontend:3000" in caddy
    assert "  app: {}" in compose
    assert "  data:\n    internal: true" in compose
    assert "networks: [data]" in postgres_block
    assert "networks: [app, data]" in frontend_block
    assert "networks: [app]" in frontend_only
    assert "networks: [app]" in proxy_only


def _synthetic_archive(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for root, filename, content in (
            ("document-storage", "doc-key", b"synthetic-document"),
            ("generated-artifact-storage", "artifact-key", b"synthetic-artifact"),
        ):
            directory = tarfile.TarInfo(root)
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o700
            archive.addfile(directory)
            item = tarfile.TarInfo(f"{root}/{filename}")
            item.size = len(content)
            item.mode = 0o600
            archive.addfile(item, io.BytesIO(content))


def test_backup_manifest_hashes_and_safe_storage_restore(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "postgres.dump").write_bytes(b"synthetic-pg-dump")
    _synthetic_archive(backup / "private-storage.tar.gz")
    manifest = create_manifest(
        backup,
        timestamp="2026-10-04T10:00:00Z",
        application_commit="a" * 40,
        alembic_revision="0009_canada_preparation_runs",
    )
    verified = verify_manifest(manifest)
    assert set(verified["files"]) == {"database", "storage"}
    assert "password" not in manifest.read_text().casefold()
    documents, generated = tmp_path / "restored-documents", tmp_path / "restored-generated"
    documents.mkdir(); generated.mkdir()
    restore_storage(manifest, documents, generated)
    assert (documents / "doc-key").read_bytes() == b"synthetic-document"
    assert (generated / "artifact-key").read_bytes() == b"synthetic-artifact"
    assert (documents / "doc-key").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="empty"):
        restore_storage(manifest, documents, tmp_path / "unused")
    (backup / "postgres.dump").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash_mismatch"):
        verify_manifest(manifest)


def test_restore_rejects_archive_path_traversal(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "postgres.dump").write_bytes(b"synthetic-pg-dump")
    with tarfile.open(backup / "private-storage.tar.gz", "w:gz") as archive:
        item = tarfile.TarInfo("document-storage/../../escape")
        item.size = 1
        archive.addfile(item, io.BytesIO(b"x"))
    manifest = create_manifest(
        backup,
        timestamp="2026-10-04T10:00:00Z",
        application_commit="b" * 40,
        alembic_revision="0009_canada_preparation_runs",
    )
    documents, generated = tmp_path / "documents", tmp_path / "generated"
    documents.mkdir(); generated.mkdir()
    with pytest.raises(ValueError, match="unsafe_storage_archive_path"):
        restore_storage(manifest, documents, generated)


def test_d1_report_is_sanitized_and_acceptance_fails_for_not_run(tmp_path):
    report_path = tmp_path / "d1-result.json"
    report = initial_report(PROJECT_ROOT)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    update_report(report_path, "service_health.backend", "PASS")
    rendered = report_path.read_text(encoding="utf-8")
    for forbidden in ("DATABASE_URL", "storage_key", "password", "api_key"):
        assert forbidden.casefold() not in rendered.casefold()
    with pytest.raises(ValueError, match="unsupported_report_field"):
        update_report(report_path, "database_url", "postgresql://secret")
    accepted, checks = acceptance(report_path)
    assert accepted is False
    assert any(item["status"] == "NOT RUN" for item in checks)


def test_deployment_scripts_guard_destructive_operations():
    scripts = {
        path.name: path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "deployment").glob("*.sh")
    }
    combined = "\n".join(scripts.values())
    for forbidden in ("docker compose down", "docker volume rm", "DROP DATABASE", "DROP SCHEMA"):
        assert forbidden not in combined
    assert "rm -rf" not in "\n".join(
        value for name, value in scripts.items() if name != "raspberry-smoke.sh"
    )
    smoke = scripts["raspberry-smoke.sh"]
    assert 'assert_unauthenticated "/documents/$document_id/content"' in smoke
    assert 'assert_unauthenticated "/preparation-runs/$run_id/artifacts"' in smoke
    assert '[ "$status" = 401 ]' in smoke
    restore = scripts["restore-test.sh"]
    assert "--confirm-empty-target" in restore
    assert '"$destination_database" = "$current_database"' in restore
    backup = scripts["backup-staging.sh"]
    assert ".partial-" in backup
    assert "backup_manifest.py create" in backup
    assert 'mv "$partial" "$destination"' in backup
    entrypoint = (PROJECT_ROOT / "deployment/backend-entrypoint.sh").read_text()
    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
    assert 'exec "$@"' in entrypoint
    assert "alembic -c backend/alembic.ini upgrade head" in entrypoint


def test_deployment_logging_does_not_print_secret_environment_or_smoke_payload():
    scripts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "deployment").glob("*.sh")
    )
    output_lines = [
        line for line in scripts.splitlines()
        if re.search(r"\b(echo|printf)\b", line) and not line.lstrip().startswith("#")
    ]
    rendered = "\n".join(output_lines)
    for secret_name in ("DATABASE_URL", "POSTGRES_PASSWORD", "AI_API_KEY"):
        assert secret_name not in rendered
    smoke_output_lines = [line for line in output_lines if '"$smoke_json"' in line]
    assert smoke_output_lines
    assert all("| python3" in line for line in smoke_output_lines)


def test_supported_pymupdf_import_does_not_write_stdout():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pymupdf; import canada.pdf_drafts; "
            "import backend.scripts.synthetic_staging_case",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""


def test_synthetic_command_stdout_is_exactly_one_json_document(monkeypatch, capsys):
    payload = {
        "case_id": "case-id",
        "document_id": "document-id",
        "run_id": "run-id",
        "artifact_types": list(EXPECTED_ARTIFACT_TYPES),
        "package_status": "current",
    }
    monkeypatch.setattr(
        synthetic_staging_case,
        "create_synthetic_case",
        lambda *, continuation: payload if continuation else None,
    )
    monkeypatch.setattr(sys, "argv", ["synthetic_staging_case", "--continuation"])

    synthetic_staging_case.main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == json.dumps(payload, sort_keys=True) + "\n"
    assert json.loads(captured.out) == payload
    assert set(json.loads(captured.out)) >= {
        "case_id", "document_id", "run_id", "artifact_types"
    }


def test_synthetic_command_does_not_hide_generation_failure(monkeypatch, capsys):
    def fail(*, continuation):
        raise RuntimeError("synthetic generation failed")

    monkeypatch.setattr(synthetic_staging_case, "create_synthetic_case", fail)
    monkeypatch.setattr(sys, "argv", ["synthetic_staging_case", "--continuation"])

    with pytest.raises(RuntimeError, match="synthetic generation failed"):
        synthetic_staging_case.main()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "empty"),
        ("not-json", "exactly one JSON document"),
        ('{"case_id": "case-id"} trailing', "exactly one JSON document"),
        (
            'warning: deprecated import\n{"case_id": "case-id"}',
            "exactly one JSON document",
        ),
    ],
)
def test_synthetic_smoke_contract_rejects_invalid_output(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_producer_output(raw)


def test_synthetic_smoke_contract_requires_keys_and_expected_artifacts():
    with pytest.raises(ValueError, match="document_id, run_id, artifact_types"):
        parse_producer_output('{"case_id": "case-id"}')

    payload = {
        "case_id": "case-id",
        "document_id": "document-id",
        "run_id": "run-id",
        "artifact_types": list(EXPECTED_ARTIFACT_TYPES),
    }
    assert parse_producer_output(json.dumps(payload)) == payload
    assert tuple(payload["artifact_types"]) == EXPECTED_ARTIFACT_TYPES

    payload["artifact_types"] = ["imm5257"]
    with pytest.raises(ValueError, match="unexpected artifact_types"):
        parse_producer_output(json.dumps(payload))


@pytest.mark.parametrize(
    ("continuation", "expected"),
    [
        (False, {"imm5257", "imm5707", "imm5476"}),
        (True, {"imm5257", "imm5707", "imm5476", "imm5257_continuation"}),
    ],
)
def test_synthetic_deployment_fixture_generates_and_verifies(
    tmp_path, monkeypatch, capsys, continuation, expected
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'smoke.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(synthetic_staging_case, "SessionLocal", factory)
    monkeypatch.setattr(verify_synthetic_staging, "SessionLocal", factory)
    monkeypatch.setattr(verify_restored_staging, "SessionLocal", factory)
    monkeypatch.setenv("DOCUMENT_STORAGE_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("GENERATED_ARTIFACT_STORAGE_ROOT", str(tmp_path / "generated"))
    result = synthetic_staging_case.create_synthetic_case(continuation=continuation)
    assert capsys.readouterr().out == ""
    assert result["package_status"] == "current"
    assert result["workflow_state"] == "PREPARE"
    assert result["requirement_count"] > 0
    assert set(result["artifact_types"]) == expected
    verified = verify_synthetic_staging.verify(
        result["case_id"], result["run_id"], result["document_id"]
    )
    assert verified["package_status"] == "current"
    assert set(verified["artifact_types"]) == expected
    with factory.begin() as session:
        session.execute(text(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": "0011_authorization_audit"},
        )
    restored = verify_restored_staging.verify()
    assert restored["status"] == "PASS"
    assert restored["alembic_revision"] == "0011_authorization_audit"
    assert restored["current_package_count"] == 1
    assert set(restored["artifact_types"]) == expected
    engine.dispose()


def test_public_repository_hygiene_has_no_high_confidence_secrets():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    forbidden_suffixes = (".db", ".sqlite", ".sqlite3", ".dump", ".p12", ".pfx", ".key")
    assert not [name for name in tracked if name.casefold().endswith(forbidden_suffixes)]
    assert not [name for name in tracked if name in {".env", ".env.production"}]
    high_confidence = re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
        rb"AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{30,}|"
        rb"sk-[A-Za-z0-9]{32,}|AIza[0-9A-Za-z_-]{30,}"
    )
    for name in tracked:
        source = PROJECT_ROOT / name
        if source.is_file() and source.stat().st_size < 5 * 1024 * 1024:
            assert high_confidence.search(source.read_bytes()) is None, name
    sample = (PROJECT_ROOT / "examples/sample_google_forms.csv").read_text().casefold()
    assert "example.invalid" in sample
    assert "gmail.com" not in sample
    ignore = (PROJECT_ROOT / ".gitignore").read_text()
    for pattern in (
        ".env", "*.db", "*.sqlite", "/backend/storage/",
        "/backend/generated-storage/", "/deployment/reports/",
        "*.whatsapp-export.txt", "*.canada-case.json",
    ):
        assert pattern in ignore
