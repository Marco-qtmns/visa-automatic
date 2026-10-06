from __future__ import annotations

from backend.app.runtime_dependencies import check_auth_runtime_dependencies


def main() -> int:
    ok, code, details = check_auth_runtime_dependencies()
    suffix = f": {', '.join(details)}" if details else ""
    print(f"{'PASS' if ok else 'FAIL'} {code}{suffix}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
