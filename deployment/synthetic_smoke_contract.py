"""Validate the machine-readable output of the D1 synthetic generator."""
from __future__ import annotations

import json
import sys
from typing import Any


REQUIRED_KEYS = ("case_id", "document_id", "run_id", "artifact_types")
EXPECTED_ARTIFACT_TYPES = (
    "imm5257",
    "imm5257_continuation",
    "imm5476",
    "imm5707",
)


def parse_producer_output(raw: str) -> dict[str, Any]:
    if not raw.strip():
        raise ValueError("producer output is empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"producer output is not exactly one JSON document: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("producer JSON must be an object")

    missing = [key for key in REQUIRED_KEYS if key not in payload]
    if missing:
        raise ValueError(f"producer JSON is missing required keys: {', '.join(missing)}")
    for key in ("case_id", "document_id", "run_id"):
        if not isinstance(payload[key], str) or not payload[key]:
            raise ValueError(f"producer JSON key {key} must be a non-empty string")

    artifact_types = payload["artifact_types"]
    if not isinstance(artifact_types, list) or not all(
        isinstance(value, str) for value in artifact_types
    ):
        raise ValueError("producer JSON key artifact_types must be a list of strings")
    if tuple(artifact_types) != EXPECTED_ARTIFACT_TYPES:
        raise ValueError(
            "producer JSON has unexpected artifact_types: " + ",".join(artifact_types)
        )
    return payload


def main() -> int:
    try:
        payload = parse_producer_output(sys.stdin.read())
    except ValueError as exc:
        print(f"Synthetic smoke output invalid: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
