# Visa Automatic

Visa Automatic is a case-management and document-preparation system for visa
application workflows. The current implementation focuses on a canonical,
auditable Canada workflow operated through an employee web application.

> **Development status:** The application is not yet approved for production
> handling of real multi-user customer data because authentication and final
> deployment hardening are not complete.

## Current capabilities

The Canada architecture currently includes:

- a canonical CASE / PERSON / FACT / REQUIREMENT / DOCUMENT / TASK model;
- a deterministic workflow state machine and centralized next-action logic;
- an employee Next.js web UI backed by FastAPI and PostgreSQL;
- controlled document upload, metadata assignment, matching, classification,
  quality review, and requirement-completeness evaluation;
- WhatsApp text import with deterministic parsing and employee-reviewed fact
  extraction;
- a canonical `CanadaApplication` domain model;
- controlled legacy and Google intake import with preview and conflict review;
- a preparation-readiness policy and immutable
  `CanonicalPreparationPayload`;
- integration with the existing Canada PDF generator through a dedicated
  adapter;
- versioned `PreparationRun` and generated-artifact history; and
- IMM5257, IMM5707, and IMM5476 generation, with conditional IMM5257
  continuation generation.

Actions that affect facts, document classifications, quality decisions,
imports, workflow state, or preparation remain explicit and auditable. The
system does not submit visa applications externally.

## Architecture

```text
Employee browser
    ↓
Next.js
    ↓
FastAPI
    ↓
PostgreSQL
    ↓
private document/generated-artifact storage
```

The backend owns domain validation, workflow rules, readiness decisions, and
generation status. The frontend does not duplicate those rules. Uploaded
documents and generated artifacts are served through controlled backend
endpoints rather than exposed as static files.

## Canada application workflow

The preparation path is deterministic and based only on reviewed canonical
data:

```text
canonical CASE
→ readiness
→ CanonicalPreparationPayload
→ CanadaFormGeneratorAdapter
→ existing PDF generator
→ StorageProvider
→ PreparationRun / PreparationArtifact
```

Readiness blocks incomplete or unresolved preparation data. A successful run
records the payload, policy, adapter, template, and artifact hashes needed to
detect stale or damaged output. Generation produces draft forms only; it does
not generate Canada letters or perform external submission.

## Repository structure

- `backend/` — FastAPI API, SQLAlchemy domain model, services, migrations, and
  backend tests.
- `frontend/` — Next.js/React employee interface and frontend tests.
- `canada/` — existing Canada intake, review, validation, and PDF-generation
  components used behind the backend adapter.
- `australia/` — standalone Australian Form 956A compatibility code.
- `deployment/` — D1 staging preflight, diagnostics, smoke, backup, restore,
  and acceptance tooling.
- `templates/` — Canada and Australia PDF form templates.
- `tests/` — cross-cutting and legacy compatibility tests.
- `docs/` — Canada workflow, coverage, reconciliation, and review notes.

## Local development

Prerequisites are Python 3.13, Node.js/npm, and a local PostgreSQL database.
Python 3.13 is the supported development and deployment version; Python 3.14
is not currently part of the tested dependency target. The current container
builds use Python 3.13, Node.js 22, and PostgreSQL 17.

Start the backend from the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/visa_automatic'
export CORS_ORIGINS='http://localhost:3000,http://127.0.0.1:3000'
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
```

Use local development credentials, and create the referenced PostgreSQL
database before applying migrations. Never commit a populated environment
file. Run backend commands from the repository root. The FastAPI package is
`backend.app`; the root-level `app.py` is the standalone desktop compatibility
application, so `import app` from the repository root intentionally does not
refer to the backend.

In another terminal, start the employee frontend:

```bash
cp frontend/.env.example frontend/.env.local
npm --prefix frontend ci
npm --prefix frontend run dev
```

The backend API is available at `http://localhost:8000` (including
`http://localhost:8000/health/live`) and the employee UI at
`http://localhost:3000/cases`. Useful verification commands are:

```bash
pytest -q
npm --prefix frontend run test:run
npm --prefix frontend run build
```

The full Docker Compose stack is the D1 staging configuration, not a production
deployment. Its environment, persistence, and validation procedure are covered
in the deployment guide below.

## Raspberry Pi staging deployment

[DEPLOYMENT_D1.md](DEPLOYMENT_D1.md) describes the Compose-based staging stack,
preflight checks, persistence, diagnostics, smoke testing, backup, and restore
validation.

The current staging target is a Raspberry Pi 4 with 8 GB RAM running 64-bit
Linux ARM64 with SSD/NVMe-backed persistence. D1.1 Mac-side deployment
hardening is complete, but real on-device Raspberry Pi/Linux ARM64 validation
is still pending. **D1 is not accepted and this is not a production
deployment.**

## Current project status

Completed:

- M1 through M9D;
- D1.1 Mac-side deployment hardening.

Not yet accepted or completed:

- real Raspberry Pi / Linux ARM64 D1 deployment validation;
- application authentication, users, roles, and MFA;
- production deployment;
- direct WhatsApp Business API integration;
- external LLM provider integration;
- letter generation;
- external visa submission; and
- Tauri/Windows packaging.

## Legacy Australian 956A generator

The standalone Australian Form 956A generator remains in this repository for
compatibility and history. It is not the identity or primary purpose of this
repository. New Visa Automatic development centers on the backend/frontend
case-management and document-preparation architecture.

## Security and privacy

- Use synthetic data for development and staging.
- Do not commit customer data, secrets, populated environment files, uploads,
  backups, database dumps, WhatsApp exports, or generated customer PDFs.
- External AI and fact-extraction providers are disabled by default.
- Private storage must remain behind the backend; do not expose storage roots
  through the web server.
- Do not expose the staging stack to the public Internet.

## Documentation

- [Backend overview](backend/README.md)
- [Workflow architecture](backend/WORKFLOW.md)
- [Document storage and matching](backend/DOCUMENTS.md)
- [Document classification](backend/CLASSIFICATION.md)
- [Document quality and completeness](backend/QUALITY.md)
- [WhatsApp import and fact review](backend/WHATSAPP.md)
- [Canonical Canada application](backend/CANADA_APPLICATION.md)
- [Controlled Canada intake imports](backend/CANADA_IMPORTS.md)
- [Canada preparation readiness](backend/CANADA_PREPARATION.md)
- [Canada form generation](backend/CANADA_GENERATION.md)
- [D1 staging deployment](DEPLOYMENT_D1.md)
