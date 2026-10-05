from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from deployment.d1_report import update_report
except ModuleNotFoundError:  # Direct execution from the repository root.
    from d1_report import update_report


REQUIRED_STATUS_FIELDS = (
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
)
REQUIRED_VALUE_FIELDS = (
    "alembic_revision",
    "pymupdf_version",
    "reportlab_version",
)


def _value(report: dict[str, object], field: str) -> object:
    value: object = report
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def acceptance(report_path: Path) -> tuple[bool, list[dict[str, str]]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checks: list[dict[str, str]] = []
    for field in REQUIRED_STATUS_FIELDS:
        value = _value(report, field)
        checks.append({"name": field, "status": "PASS" if value == "PASS" else str(value)})
    for field in REQUIRED_VALUE_FIELDS:
        value = _value(report, field)
        ok = isinstance(value, str) and value not in {"", "NOT RUN", "NOT AVAILABLE"}
        checks.append({"name": field, "status": "PASS" if ok else "NOT RUN"})
    return all(item["status"] == "PASS" for item in checks), checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the sanitized D1 acceptance report.")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    accepted, checks = acceptance(args.report)
    update_report(args.report, "overall_status", "PASS" if accepted else "FAIL")
    print(json.dumps({"accepted": accepted, "checks": checks}, sort_keys=True))
    raise SystemExit(0 if accepted else 1)


if __name__ == "__main__":
    main()
