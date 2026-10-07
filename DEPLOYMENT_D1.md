# D1 Raspberry Pi 4 development/staging deployment

> **D1 IS NOT APPROVED FOR REAL MULTI-USER CUSTOMER DATA.**
>
> Visa Automatic has no application authentication, users, roles, MFA, or
> tenant isolation. A private LAN or Tailscale is not a replacement for
> application authentication. Use synthetic data only and never expose this
> stack to the public Internet.

## Target and validation status

The target is a Raspberry Pi 4 Model B with 8 GB RAM, 64-bit aarch64 Linux,
glibc, Docker Compose, and USB 3 SSD/NVMe persistent storage. It is a controlled
development/staging target, not production infrastructure.

D1/D1.1 was prepared and tested on macOS ARM64 without Docker or a Raspberry
Pi. Therefore D1 is **NOT ACCEPTED**. Results are separated as follows:

- **Verified on Mac:** backend/frontend/legacy tests, Next.js production build,
  Python compilation, both real synthetic generator modes, environment checks,
  archive/manifest/restore helpers, and privacy/static tests.
- **Statically verified:** Compose/Dockerfile/Caddy structure, environment
  contract, paths, network exposure, migration chain, dependency metadata,
  logging, and repository hygiene.
- **Requires Docker:** image builds, Compose semantic validation, PostgreSQL,
  Alembic execution, service health, proxy integration, and backup execution.
- **Requires Raspberry:** native ARM64 imports, Pi/SSD checks, cross-machine UI,
  restart and recreation persistence.
- **Requires separate restore environment:** PostgreSQL and storage restore.

See [deployment/STATIC_AUDIT_D1_1.md](deployment/STATIC_AUDIT_D1_1.md) for the
detailed static audit.

Selected images:

- backend: `python:3.13.16-slim-bookworm` (Debian/glibc, never Alpine)
- frontend: `node:22.23.3-bookworm-slim`
- database: `postgres:17.11-bookworm`
- proxy: `caddy:2.11.6-alpine` (PyMuPDF does not run in this container)

Python deployment dependencies are pinned in `requirements.deploy.txt`; the
frontend uses `package-lock.json`. Do not force an x86 emulation platform.

## Architecture, network, and persistence

```text
private/Tailscale client -> APP_PORT -> Caddy
                                  |-> /api/* -> FastAPI :8000
                                  `-> /*     -> Next.js :3000

FastAPI -> PostgreSQL :5432 (internal network only)
        -> /srv/visa-automatic/document-storage
        -> /srv/visa-automatic/generated-artifact-storage
        -> /srv/visa-automatic/intake-storage
```

Only Caddy publishes a host port. Caddy, frontend, and backend share an app
bridge; backend and PostgreSQL additionally share an internal data network.
PostgreSQL has no route through the app network. Caddy never serves private
storage statically; downloads go through application endpoints.

`DATA_ROOT` must be an SSD/NVMe-backed absolute host path:

```text
DATA_ROOT/
  postgres-data/
  document-storage/
  generated-artifact-storage/
  intake-storage/
  backups/
```

The backend runs as UID/GID 10001. The selected PostgreSQL image currently uses
UID/GID 999; preflight compares the real image UID with the host directory.
Private directories use `0700`, stored files and reports `0600`. Persistent
state never belongs in the Git checkout or an ephemeral container layer.

## Environment contract and safe Mac validation

`deployment/environment-contract.json` is authoritative. For every deployment
variable it records service, required/optional state, safe example, default,
secrecy, validation, and missing-value behavior. Tests compare the contract
with `.env.production.example` and source/Compose reads.

Validate the placeholder example on the Mac without connecting to services:

```bash
PYTHONPATH=. .venv/bin/python -m backend.scripts.deployment_preflight \
  --env-file .env.production.example --allow-placeholders
```

The production-like file must be `.env.production`, mode `0600`, with a unique
password. URL-encode the password separately inside `DATABASE_URL`. Keep AI
credentials empty and providers disabled/manual for D1.

## Pi 4 hardware and OS checklist

Use a current 64-bit Raspberry Pi OS or Debian-derived aarch64 OS. Use a
suitable official-quality power supply, prefer wired Ethernet, and keep
persistent data on a USB 3 SSD/NVMe enclosure rather than microSD where
possible. Inspect, but do not record as passed until run on the Pi:

```bash
uname -m
cat /etc/os-release
getconf GNU_LIBC_VERSION
lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS
df -h /srv/visa-automatic
free -h
vcgencmd measure_temp       # if Raspberry Pi utilities are installed
vcgencmd get_throttled      # 0x0 is desired
```

`uname -m` must be `aarch64`/`arm64`. Confirm the data mount is the intended
SSD/NVMe, free space is sufficient, temperature is reasonable, and throttling
is absent.

## First installation

```bash
git clone <repository-url> visa-automatic
cd visa-automatic/Programm
cp .env.production.example .env.production
chmod 600 .env.production
# Edit placeholders; do not commit the populated file.
./deployment/prepare-host.sh /srv/visa-automatic/data
./deployment/raspberry-preflight.sh \
  --env-file .env.production \
  --report deployment/reports/d1-result.json
```

Preflight checks OS, architecture, glibc, memory, disk/mount, Docker/Compose,
daemon access, Git state, env file, Compose config, directories/permissions,
image UID, image builds, service startup, Alembic 0009, proxy health, PyMuPDF,
ReportLab, template hashes, and synthetic storage write/read/delete. It prints
`PASS`, `FAIL`, or `SKIP`, stops on unsafe critical failures, and never prints
environment values. It performs no reset, drop, or volume/storage deletion.

The backend entrypoint first runs the safe deployment configuration validator
with writable-path checks, then executes:

```bash
alembic -c backend/alembic.ini upgrade head
```

Migration failure stops the backend before Uvicorn. The entrypoint never drops
or recreates the database. Expected head: `0009_canada_preparation_runs`.

Revision `0005_doc_quality_completeness` replaces the former 34-character
identifier `0005_document_quality_completeness`, which cannot be stored in the
project's standard Alembic `VARCHAR(32)` version column. Clean databases and
databases at revisions `0001` through `0004` upgrade normally. A nonstandard
database that was manually widened and stamped with the former identifier must
be reconciled by an operator only after verifying its applied schema; do not
blindly rewrite its version row.

## Routing and remote access

The frontend is built with `NEXT_PUBLIC_API_BASE_URL=/api`. Caddy strips `/api`
before forwarding to FastAPI, so a remote employee browser never calls its own
`localhost:8000`.

For initial remote access, keep `BIND_ADDRESS=127.0.0.1` and configure Tailscale
Serve manually:

```bash
sudo tailscale serve --bg http://127.0.0.1:8080
tailscale serve status
```

Use its exact HTTPS origin in `CORS_ORIGINS`. Do not enable Funnel, router port
forwarding, or public firewall exposure. Tailscale account/policy remains a
manual operator responsibility.

## Health and diagnostics

- `/api/health/live`: cheap process-only liveness.
- `/api/health/ready`: DB access, exact Alembic head, write/delete probes for
  both roots, generator imports, and three template SHA-256 checks.
- PostgreSQL: `pg_isready`.
- Frontend: internal HTTP response.
- Proxy: backend liveness through Caddy.

Failures expose stable component/code/status values, not paths, URLs,
credentials, payloads, or traces.

```bash
./deployment/diagnose.sh .env.production
```

## Synthetic generation and persistence test

The application-level command below creates a new, wholly synthetic case on
each invocation using domain/application services; it never resets prior data:

```bash
docker compose --env-file .env.production exec -T backend \
  python -m backend.scripts.synthetic_staging_case --continuation
```

It uses obviously fictional values, creates applicant/canonical biography,
citizenship, passport, contacts, residential/mailing state, trip, no-host and
applicant-funding states, representative, official answers, evaluated
requirements, workflow transitions, preparation readiness, and M9D generation.
Output contains safe identifiers, counts, status, and artifact types only.

Run the supported complete smoke/persistence sequence:

```bash
./deployment/raspberry-smoke.sh \
  --env-file .env.production \
  --report deployment/reports/d1-result.json \
  --force-recreate
```

It verifies IMM5257, IMM5707, IMM5476 and forced continuation; PDF presence and
SHA-256; `current` status; authentication enforcement on protected document and
artifact APIs; case, canonical
application, requirements, document, run, artifacts, and hashes before restart;
then the same state and byte-identical stored content after restart and explicit
container recreation. It never removes volumes or persistent data.

Also load the employee UI and download the synthetic artifacts from a second
machine through the single Caddy/Tailscale origin. Record this manual result.

## Backup

```bash
./deployment/backup-staging.sh \
  --env-file .env.production \
  --report deployment/reports/d1-result.json
```

The script creates a timestamped PostgreSQL custom-format dump and compressed
archive of both storage roots. Work remains hidden in a `.partial-*` directory
until every command, manifest, and SHA-256 succeeds; only then is it atomically
moved into place. Failure is never reported as success and source files are
never deleted. The manifest contains timestamp, commit, Alembic revision,
filenames, and hashes—never database URL or password.

## Separate empty-target restore

Never restore over the live staging database or live storage. Create an empty
database owned by the configured staging DB user and three empty absolute
directories outside live `DATA_ROOT`, then run:

```bash
./deployment/restore-test.sh \
  --env-file .env.production \
  --manifest /separate/backup/manifest.json \
  --destination-database visa_automatic_restore_test \
  --documents /separate/restore/document-storage \
  --generated /separate/restore/generated-artifact-storage \
  --intake /separate/restore/intake-storage \
  --report deployment/reports/d1-result.json \
  --confirm-empty-target
```

The script verifies hashes, refuses the configured live database, requires
empty distinct roots, checks that the destination has no public tables, uses
`pg_restore --exit-on-error` without cleanup/drop, and extracts only safe regular
files/directories with private modes. A short-lived root helper from the backend
image receives only the two validated restore mounts, normalizes their ownership
to the centrally configured backend runtime UID/GID, and reapplies directory
mode `0700` and file mode `0600`. It never receives live `DATA_ROOT`. The helper
then exits, and the isolated verifier runs as the image's normal non-root user
against the destination database and destination mounts, checking schema,
synthetic table counts, document/artifact existence, artifact hashes, and a
current package. Restore refuses to continue if the built image identity differs
from `deployment/backend-runtime-identity.env`.
A successful PostgreSQL restore remains unverified until this is actually done.

## Update and rollback

Normal update loop:

```text
Mac: commit -> test -> push
Pi:  git pull --ff-only
     ./deployment/backup-staging.sh --env-file .env.production
     docker compose --env-file .env.production build
     docker compose --env-file .env.production up -d
     ./deployment/diagnose.sh .env.production
```

Never copy `.venv`, `node_modules`, `.next`, databases, uploads, or generated
output from the Mac. Before an update, record the current Git commit and image
IDs. If it fails, do not reset the DB or delete storage: collect safe status,
check out the recorded prior commit, rebuild its images, and start them against
unchanged bind mounts. Database downgrade/restore requires a separately
approved procedure.

## Failure recovery and safe logs

```bash
docker compose --env-file .env.production ps
./deployment/diagnose.sh .env.production
docker compose --env-file .env.production logs --tail=200 backend frontend proxy
```

Review logs before sharing. Do not attach `.env` files, dumps, archives,
request bodies, source intake, or PDFs. Operational logs may contain safe IDs,
HTTP status, timings, versions, and error codes—not payloads, passports,
addresses, finances, raw WhatsApp/Google intake, or PDF bytes.

## Machine-readable report and acceptance

`deployment/reports/` is ignored by Git. The sanitized JSON report contains
timestamp, host/OS/architecture/kernel/glibc, Docker/Compose versions, commit,
Alembic/dependency versions, component states, generation, continuation,
persistence, backup, restore, and overall status. It never accepts customer
values, payloads, document names, database URLs, passwords, or storage keys.

Final sequence:

```bash
./deployment/raspberry-preflight.sh --env-file .env.production \
  --report deployment/reports/d1-result.json
./deployment/raspberry-smoke.sh --env-file .env.production \
  --report deployment/reports/d1-result.json --force-recreate
./deployment/backup-staging.sh --env-file .env.production \
  --report deployment/reports/d1-result.json
./deployment/restore-test.sh --env-file .env.production \
  --manifest /separate/backup/manifest.json \
  --destination-database visa_automatic_restore_test \
  --documents /separate/restore/document-storage \
  --generated /separate/restore/generated-artifact-storage \
  --intake /separate/restore/intake-storage \
  --report deployment/reports/d1-result.json --confirm-empty-target
python3 deployment/d1_acceptance.py --report deployment/reports/d1-result.json
```

The evaluator distinguishes `PASS`, `FAIL`, `NOT RUN`, and `NOT APPLICABLE`.
D1 can become accepted only when it succeeds after all mandatory hardware,
runtime, persistence, backup, and separate restore checks actually pass.

D1 adds no authentication, user management, roles, MFA, WhatsApp API, external
AI, letter generation, submission, Tauri, Windows installer, or cloud platform.
