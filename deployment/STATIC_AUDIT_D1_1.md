# D1.1 static deployment audit

Audit date: 2026-10-04. This source/configuration audit was performed on macOS
ARM64 without Docker or Raspberry Pi hardware. Static compatibility is not an
on-device pass.

## Deployment configuration findings

| Area | Result | Notes |
|---|---|---|
| Compose | Hardened | Four services; an app bridge connects proxy/frontend/backend, while an internal data network connects only backend/PostgreSQL. Only proxy publishes a host port. |
| Backend image | Statically valid | Debian/glibc Python 3.13, non-root UID/GID 10001, pinned direct dependencies, repository-relative Canada/template copies. |
| Frontend image | Statically valid | Pinned Node 22 Debian image, multi-stage `npm ci` build, standalone non-root runtime, build-time `/api`. |
| Caddy | Statically valid | `/api/*` is stripped before FastAPI; all other paths reach Next.js; no static storage route exists. |
| Entrypoint | Statically valid | `set -eu`; Alembic failure prevents Uvicorn startup; no reset/drop behavior. |
| Environment | Hardened | The JSON contract is authoritative and tested against the example and source reads; preflight never prints values. |
| Persistence | Statically valid | PostgreSQL, documents, generated artifacts, and backups use distinct host paths; generator temporary files remain ephemeral. |
| Health | Statically valid | Live is process-only; ready returns safe component codes and checks DB/head, storage, imports, templates, and hashes. |
| Backup | Hardened | Partial directory, restrictive modes, database plus both storage roots, manifest/SHA-256, no source deletion. |
| Restore | Hardened | Explicit separate database and empty absolute roots, hash verification, no live overwrite or database drop, plus isolated backend verification against the restored targets. |

Confirmed fixes cover an accidentally re-included example environment file in
the backend Docker context, missing cache/backup/PDF exclusions, absent
environment-contract drift checks, non-atomic/unmanifested backups, and missing
safe restore automation. The original all-internal network was also split so a
published proxy can reach host interfaces while PostgreSQL stays on an internal
data network. No deployment file contains a macOS home-directory path.

## Migration safety review: 0001 through 0009

- There is one linear head: `0009_canada_preparation_runs`.
- Upgrade order is continuous. No upgrade drops a table, populated column, or
  schema, resets data, or depends on environment values.
- PostgreSQL UUID/JSONB in 0001–0006 is intentional. SQLite is a test
  convenience, not a deployment migration target.
- Downgrades are destructive by definition, but no deployment script invokes
  downgrade.
- **Known migration-drift risk:** accepted migrations 0007, 0008, and 0009
  import current `Base.metadata`. Table-name lists are fixed, but column/index
  declarations can drift when runtime models change. This is not currently
  proven to break the accepted chain, so historical migrations were not edited.
  Before future model changes, approve a repair strategy or freeze declarations
  through a new controlled PostgreSQL migration test.
- Clean and existing-database PostgreSQL upgrades remain Docker/Pi checks.

## Dependency reproducibility

- Backend image: `python:3.13.16-slim-bookworm`.
- Deployment requirements pin FastAPI 0.142.2, SQLAlchemy 2.1.1, Alembic 1.20.0,
  psycopg 3.3.6, PyMuPDF 1.28.2, ReportLab 4.5.1, Pydantic 2.13.5, Pillow 12.3.0,
  python-multipart 0.0.32, and Uvicorn 0.54.0.
- Frontend image: `node:22.23.3-bookworm-slim`; lockfile v3 fixes Next.js
  16.3.8, React/React DOM 19.3.0, and transitive packages.
- The direct Python runtime dependency closure is also version-pinned. Wheels
  are not hash-locked; the native image build remains the definitive install
  and platform check.

## ARM64 and platform classification

| Finding | Classification | Assessment |
|---|---|---|
| Backend domain/API/services | portable | No subprocess, shell execution, AppleScript, desktop opener, or absolute developer path. |
| Canada M9D generator | portable with native dependency | Python APIs only. PyMuPDF and Pillow publish glibc ARM64 wheels; ReportLab is platform-independent. Pi imports remain required. |
| psycopg binary | portable with native dependency | A CPython 3.13 manylinux ARM64 wheel is published; actual install/connect remains a Pi check. |
| `deployment/*.sh` | deployment-only | POSIX/Linux utilities are intentionally isolated from business logic. |
| root `app.py`, `settings.py` | legacy-only | Desktop opener branches are outside the backend deployment. |
| `tools/build_windows.py` | legacy/release-only | Windows packaging is not copied into or invoked by the backend image. |
| SQLite PRAGMA calls | test-only | Used by tests, not deployed runtime. |

No static ARM64 blocker was found. This does not claim Raspberry Pi success.

## Filesystem, network, logging, and repository hygiene

- Code stays in Git; PostgreSQL data, documents, artifacts, and backups stay
  under `DATA_ROOT`; storage roots are distinct and outside the checkout.
- Browser traffic is one-origin: browser → Caddy → Next.js or `/api` → FastAPI.
  Production frontend source has no localhost, developer IP, or Mac hostname.
- Default bind is loopback, CORS has no wildcard, and only the proxy publishes a
  host port.
- Backend application code has no payload logging calls. Deployment commands
  print versions, statuses, safe IDs, counts, and artifact types. Reports reject
  URLs, passwords, storage keys, and unsupported fields.
- Git/Docker ignores cover storage, reports, environments, virtualenvs, caches,
  databases, backups, arbitrary PDFs, and customer/import output. Only required
  Canada templates are explicitly re-included in the backend context.
- `examples/sample_google_forms.csv` now uses obviously synthetic `.invalid` and
  zero values. The legacy Australia smoke fixture was likewise made explicitly
  synthetic. A generated `REPOSITORY_REVIEW_956.txt` dump containing realistic
  contact data was removed and its filename family is now ignored. The ignored
  local Google Forms PDF is neither tracked nor copied.

## Unverified boundaries

Image builds, Compose semantic validation, PostgreSQL startup/migration,
container health, Caddy reachability, ARM64 imports, SSD behavior,
restart/recreation persistence, backup execution, and separate-environment
database restore require Docker and/or Raspberry Pi hardware.
