from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Callable


@dataclass(frozen=True)
class RuntimeRequirement:
    distribution: str
    import_name: str


# This is the authoritative mapping between the production distributions and
# import modules introduced by M10A. TOTP itself is intentionally implemented
# with the Python standard library and has no additional distribution.
AUTH_RUNTIME_REQUIREMENTS = (
    RuntimeRequirement("argon2-cffi", "argon2"),
    RuntimeRequirement("cryptography", "cryptography.fernet"),
    RuntimeRequirement("email-validator", "email_validator"),
)
TOTP_STANDARD_LIBRARY_MODULES = ("base64", "hashlib", "hmac", "secrets", "struct", "time")


def check_auth_runtime_dependencies(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> tuple[bool, str, tuple[str, ...]]:
    missing: list[str] = []
    for requirement in AUTH_RUNTIME_REQUIREMENTS:
        try:
            importer(requirement.import_name)
        except (ImportError, ModuleNotFoundError):
            missing.append(requirement.distribution)
    for module_name in TOTP_STANDARD_LIBRARY_MODULES:
        try:
            importer(module_name)
        except (ImportError, ModuleNotFoundError):
            missing.append(f"python:{module_name}")
    if missing:
        return False, "auth_runtime_dependency_missing", tuple(sorted(missing))

    try:
        argon2 = importer("argon2")
        fernet_module = importer("cryptography.fernet")
        backend_auth = importer("backend.app.auth")

        if backend_auth.PASSWORD_HASHER.type is not argon2.low_level.Type.ID:
            return False, "argon2id_not_configured", ()

        fernet = fernet_module.Fernet(fernet_module.Fernet.generate_key())
        if fernet.decrypt(fernet.encrypt(b"runtime-smoke")) != b"runtime-smoke":
            return False, "fernet_runtime_invalid", ()

        secret = "JBSWY3DPEHPK3PXP"
        code = backend_auth.totp_code(secret, at_time=1_700_000_000)
        if not backend_auth.verify_totp(secret, code, at_time=1_700_000_000):
            return False, "totp_runtime_invalid", ()
    except Exception:
        return False, "auth_runtime_dependency_invalid", ()
    return True, "auth_runtime_dependencies_available", ()
