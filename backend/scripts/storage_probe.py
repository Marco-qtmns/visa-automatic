from __future__ import annotations

from io import BytesIO

from backend.app.storage import LocalStorageProvider


def probe(provider: LocalStorageProvider) -> None:
    payload = b"visa-automatic-d1-synthetic-storage-probe"
    stored = provider.save(BytesIO(payload), max_bytes=1024)
    try:
        with provider.open(stored.key) as source:
            if source.read() != payload:
                raise RuntimeError("storage_probe_read_mismatch")
    finally:
        provider.delete(stored.key)
    if provider.exists(stored.key):
        raise RuntimeError("storage_probe_delete_failed")


def main() -> None:
    probe(LocalStorageProvider.from_environment())
    probe(LocalStorageProvider.generated_from_environment())
    print("synthetic storage write/read/delete: PASS")


if __name__ == "__main__":
    main()
