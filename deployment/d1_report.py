from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


STATUS_VALUES = {"PASS", "FAIL", "NOT RUN", "NOT APPLICABLE"}
STATUS_FIELDS = {
    "service_health.postgres",
    "service_health.backend",
    "service_health.frontend",
    "service_health.proxy",
    "service_health.live",
    "service_health.ready",
    "generator_smoke_result",
    "continuation_smoke_result",
    "persistence_result",
    "backup_result",
    "restore_result",
    "overall_status",
}
VERSION_FIELDS = {
    "alembic_revision",
    "pymupdf_version",
    "reportlab_version",
}
SAFE_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ,._()+:/-]{0,159}\Z")


def _safe_text(value: str, fallback: str = "NOT AVAILABLE") -> str:
    cleaned = " ".join(value.replace("\x00", " ").split())
    return cleaned if SAFE_TEXT.fullmatch(cleaned) else fallback


def _command_version(command: list[str]) -> str:
    if shutil.which(command[0]) is None:
        return "NOT AVAILABLE"
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return "NOT AVAILABLE"
    return _safe_text((result.stdout or result.stderr).splitlines()[0])


def _os_description() -> str:
    release = Path("/etc/os-release")
    if release.is_file():
        for line in release.read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return _safe_text(line.split("=", 1)[1].strip().strip('"'))
    return _safe_text(f"{platform.system()} {platform.release()}")


def _host_model() -> str:
    model = Path("/proc/device-tree/model")
    if model.is_file():
        return _safe_text(model.read_text(encoding="utf-8", errors="replace"))
    return "NOT AVAILABLE"


def _git_commit(repository: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return "NOT AVAILABLE"
    value = result.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else "NOT AVAILABLE"


def initial_report(repository: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host_model": _host_model(),
        "os": _os_description(),
        "architecture": _safe_text(platform.machine()),
        "kernel": _safe_text(platform.release()),
        "glibc_version": _safe_text(" ".join(platform.libc_ver()).strip()),
        "docker_version": _command_version(["docker", "--version"]),
        "compose_version": _command_version(["docker", "compose", "version"]),
        "application_commit_sha": _git_commit(repository),
        "alembic_revision": "NOT RUN",
        "pymupdf_version": "NOT RUN",
        "reportlab_version": "NOT RUN",
        "service_health": {
            "postgres": "NOT RUN",
            "backend": "NOT RUN",
            "frontend": "NOT RUN",
            "proxy": "NOT RUN",
            "live": "NOT RUN",
            "ready": "NOT RUN",
        },
        "generator_smoke_result": "NOT RUN",
        "continuation_smoke_result": "NOT RUN",
        "persistence_result": "NOT RUN",
        "backup_result": "NOT RUN",
        "restore_result": "NOT RUN",
        "overall_status": "NOT RUN",
    }


def _write_report(path: Path, report: dict[str, object]) -> None:
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _read_report(path: Path) -> dict[str, object]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1:
        raise ValueError("unsupported_report_schema")
    return report


def update_report(path: Path, field: str, value: str) -> None:
    report = _read_report(path)
    if field in STATUS_FIELDS:
        if value not in STATUS_VALUES:
            raise ValueError("invalid_status_value")
    elif field in VERSION_FIELDS:
        if not SAFE_TEXT.fullmatch(value) or any(
            marker in value.casefold()
            for marker in ("password", "postgresql://", "postgresql+psycopg://", "api_key")
        ):
            raise ValueError("unsafe_report_value")
    else:
        raise ValueError("unsupported_report_field")
    target: dict[str, object] = report
    parts = field.split(".")
    for part in parts[:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            raise ValueError("invalid_report_structure")
        target = nested
    target[parts[-1]] = value
    _write_report(path, report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a sanitized D1 report.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--output", type=Path, required=True)
    initialize.add_argument("--repository", type=Path, default=Path.cwd())
    update = subparsers.add_parser("update")
    update.add_argument("--report", type=Path, required=True)
    update.add_argument("--field", required=True)
    update.add_argument("--value", required=True)
    args = parser.parse_args()
    if args.command == "initialize":
        _write_report(args.output, initial_report(args.repository.resolve()))
    else:
        update_report(args.report, args.field, args.value)


if __name__ == "__main__":
    main()
