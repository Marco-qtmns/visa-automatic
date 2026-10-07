from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = 1
KINDS = {"database": "postgres.dump", "storage": "private-storage.tar.gz"}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(name: str) -> bool:
    return Path(name).name == name and bool(re.fullmatch(r"[A-Za-z0-9._-]+", name))


def create_manifest(
    backup_directory: Path,
    *,
    timestamp: str,
    application_commit: str,
    alembic_revision: str,
) -> Path:
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if not re.fullmatch(r"[0-9a-f]{40}", application_commit):
        raise ValueError("invalid_application_commit")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", alembic_revision):
        raise ValueError("invalid_alembic_revision")
    files: dict[str, dict[str, str]] = {}
    for kind, filename in KINDS.items():
        source = backup_directory / filename
        if not source.is_file():
            raise ValueError(f"missing_{kind}_backup")
        files[kind] = {"filename": filename, "sha256": _digest(source)}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "backup_timestamp": timestamp,
        "application_commit_sha": application_commit,
        "alembic_revision": alembic_revision,
        "files": files,
    }
    destination = backup_directory / "manifest.json"
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    destination.chmod(0o600)
    return destination


def verify_manifest(manifest_path: Path) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(manifest) != {
        "schema_version", "backup_timestamp", "application_commit_sha",
        "alembic_revision", "files",
    } or manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("invalid_manifest_schema")
    try:
        datetime.fromisoformat(str(manifest["backup_timestamp"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid_manifest_timestamp") from error
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest["application_commit_sha"])):
        raise ValueError("invalid_manifest_commit")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(manifest["alembic_revision"])):
        raise ValueError("invalid_manifest_revision")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != set(KINDS):
        raise ValueError("invalid_manifest_files")
    for kind, expected_filename in KINDS.items():
        item = files[kind]
        if not isinstance(item, dict) or set(item) != {"filename", "sha256"}:
            raise ValueError("invalid_manifest_file_entry")
        filename = item["filename"]
        if filename != expected_filename or not _safe_filename(filename):
            raise ValueError("unsafe_manifest_filename")
        source = manifest_path.parent / filename
        if not source.is_file() or _digest(source) != item["sha256"]:
            raise ValueError(f"{kind}_backup_hash_mismatch")
    return manifest


def backup_file(manifest_path: Path, kind: str) -> Path:
    manifest = verify_manifest(manifest_path)
    item = manifest["files"][kind]
    return manifest_path.resolve().parent / item["filename"]


def _ensure_empty_directory(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("restore_target_must_be_an_empty_directory") from error
    if not resolved.is_dir() or any(resolved.iterdir()):
        raise ValueError("restore_target_must_be_an_empty_directory")
    return resolved


def restore_storage(
    manifest_path: Path, documents: Path, generated: Path, intake: Path
) -> None:
    document_root = _ensure_empty_directory(documents)
    generated_root = _ensure_empty_directory(generated)
    intake_root = _ensure_empty_directory(intake)
    if len({document_root, generated_root, intake_root}) != 3:
        raise ValueError("restore_storage_roots_must_be_separate")
    targets = {
        "document-storage": document_root,
        "generated-artifact-storage": generated_root,
        "intake-storage": intake_root,
    }
    archive_path = backup_file(manifest_path, "storage")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("unsafe_storage_archive_path")
            if path.parts[0] not in targets:
                raise ValueError("unexpected_storage_archive_root")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("unsafe_storage_archive_member")
        for member in members:
            path = PurePosixPath(member.name)
            relative = path.parts[1:]
            if not relative:
                continue
            destination = targets[path.parts[0]].joinpath(*relative)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            if not member.isfile():
                raise ValueError("unsupported_storage_archive_member")
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("storage_archive_member_unreadable")
            with destination.open("xb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)
            destination.chmod(0o600)
    document_root.chmod(0o700)
    generated_root.chmod(0o700)
    intake_root.chmod(0o700)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, verify, or restore a D1 backup manifest.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--backup-directory", type=Path, required=True)
    create.add_argument("--timestamp", required=True)
    create.add_argument("--application-commit", required=True)
    create.add_argument("--alembic-revision", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    resolve = commands.add_parser("resolve-file")
    resolve.add_argument("--manifest", type=Path, required=True)
    resolve.add_argument("--kind", choices=sorted(KINDS), required=True)
    restore = commands.add_parser("restore-storage")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--documents", type=Path, required=True)
    restore.add_argument("--generated", type=Path, required=True)
    restore.add_argument("--intake", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        create_manifest(
            args.backup_directory,
            timestamp=args.timestamp,
            application_commit=args.application_commit,
            alembic_revision=args.alembic_revision,
        )
    elif args.command == "verify":
        verify_manifest(args.manifest)
    elif args.command == "resolve-file":
        print(backup_file(args.manifest, args.kind))
    else:
        restore_storage(args.manifest, args.documents, args.generated, args.intake)


if __name__ == "__main__":
    main()
