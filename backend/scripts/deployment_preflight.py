from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.deployment_preflight import (
    environment_from_deployment_file,
    validate_deployment_configuration,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate D1 deployment configuration safely.")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--check-writable", action="store_true")
    parser.add_argument("--allow-placeholders", action="store_true")
    args = parser.parse_args()
    environment = environment_from_deployment_file(args.env_file) if args.env_file else None
    result = validate_deployment_configuration(
        environment,
        check_writable=args.check_writable,
        allow_placeholders=args.allow_placeholders,
    )
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
