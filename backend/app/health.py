from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

from sqlalchemy import text

from .database import engine
from .deployment_preflight import EXPECTED_ALEMBIC_HEAD
from .storage import LocalStorageProvider


EXPECTED_SCHEMA_REVISION = EXPECTED_ALEMBIC_HEAD
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _database_check() -> dict[str, object]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != EXPECTED_SCHEMA_REVISION:
        raise RuntimeError("schema_revision_mismatch")
    return {"status": "ok", "revision": revision}


def _storage_check() -> dict[str, object]:
    result: dict[str, object] = {"status": "ok"}
    for label, provider in (
        ("documents", LocalStorageProvider.from_environment()),
        ("generated_artifacts", LocalStorageProvider.generated_from_environment()),
    ):
        stored = provider.save(BytesIO(b"visa-automatic-health"), max_bytes=64)
        try:
            if not provider.exists(stored.key):
                raise RuntimeError("storage_write_not_visible")
        finally:
            provider.delete(stored.key)
        result[label] = "writable"
    return result


def _generator_check() -> dict[str, object]:
    import pymupdf
    import reportlab

    matrix = json.loads((PROJECT_ROOT / "canada" / "coverage_matrix.yaml").read_text(encoding="utf-8"))
    for metadata in matrix["templates"].values():
        source = PROJECT_ROOT / metadata["file"]
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != metadata["sha256"]:
            raise RuntimeError("template_integrity_error")
    return {
        "status": "ok",
        "templates": len(matrix["templates"]),
        "pymupdf": pymupdf.VersionBind,
        "reportlab": reportlab.Version,
    }


def deployment_readiness() -> tuple[bool, dict[str, object]]:
    components: dict[str, object] = {}
    for name, check in (
        ("database", _database_check),
        ("storage", _storage_check),
        ("generator", _generator_check),
    ):
        try:
            components[name] = check()
        except Exception as error:
            # Only a constrained code is returned; connection strings, paths,
            # payloads, and source data never enter health output.
            known = {
                "schema_revision_mismatch", "storage_write_not_visible",
                "template_integrity_error",
            }
            message = str(error)
            components[name] = {
                "status": "error",
                "code": message if message in known else f"{name}_unavailable",
            }
    ready = all(value.get("status") == "ok" for value in components.values())
    return ready, {"status": "ready" if ready else "not_ready", "components": components}
