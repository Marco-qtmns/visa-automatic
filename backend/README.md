# Visa Automatic backend

Milestone 1 adds an isolated FastAPI/SQLAlchemy backend for the six core domain
entities. The existing desktop form-filling application remains the default
application and is not coupled to this backend yet.

## Run

Use Python 3.13 and run commands from the repository root. Set a PostgreSQL
connection string and apply the migration:

```bash
export DATABASE_URL='postgresql+psycopg://user:password@localhost/visa_automatic'
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
```

The backend's import path is `backend.app`. Do not add `backend/` to
`PYTHONPATH` and import a top-level package named `app`: the repository also
contains the intentionally retained desktop compatibility module `app.py`.

`DATABASE_URL` defaults to a local PostgreSQL database named `visa_automatic`.
SQLite is supported only by the isolated automated tests.

For the Milestone 3 browser client, configure allowed frontend origins as a
comma-separated list. The development default is limited to localhost ports:

```bash
export CORS_ORIGINS='http://localhost:3000,http://127.0.0.1:3000'
```

Production is a centralized service: Windows employee clients will call this
backend over HTTPS, and only the backend connects to PostgreSQL and private file
storage. PostgreSQL is not intended to be installed on employee workstations.
Copy `.env.example` for local development and never commit a populated `.env`.

## Test

```bash
pytest -q backend/tests
python -m unittest discover -s tests -v
```

No workflow transitions, requirement rules, uploads, matching, classification,
quality checks, AI behavior, or generator integration are part of Milestone 1.

Milestone 2 adds the controlled state machine and centralized Next Action logic.
See [WORKFLOW.md](WORKFLOW.md) for transition rules, gates, audit behavior, and
the temporary manual preparation-completion mechanism.

Milestone 3 adds the separate employee frontend documented in
[`../frontend/README.md`](../frontend/README.md). The API remains authoritative
for workflow transitions and Next Action decisions.

Milestone 4 adds the deterministic Canada TRV requirement engine documented in
[REQUIREMENTS.md](REQUIREMENTS.md). Version-controlled rule configuration is
strictly validated at startup. Case, person, and relevant confirmed-fact
changes trigger evaluation automatically; operators can also call
`POST /cases/{case_id}/requirements/evaluate`. No database migration is needed
because the existing Requirement entity already carries rule provenance and
lifecycle fields.

Milestone 5 adds controlled multipart upload, abstract binary storage, manual
type/person assignment, and auditable many-to-many Requirement–Document
matching. See [DOCUMENTS.md](DOCUMENTS.md). Apply migration
`0003_document_matching` before running the updated backend. Matching does not
automatically fulfil requirements and does not perform classification or
quality analysis.

Milestone 6 adds explicit, employee-reviewed document classification. Apply
migration `0004_document_classification` and see
[CLASSIFICATION.md](CLASSIFICATION.md) for extraction, provider configuration,
audit history, privacy, and review behavior. The default provider is disabled;
manual Milestone 5 assignment continues without AI configuration.

Milestone 7 adds explicit document quality checks and requirement-level
completeness. Apply migration `0005_doc_quality_completeness` and see
[QUALITY.md](QUALITY.md). The conservative local evaluator is configured with
`QUALITY_PROVIDER=manual_only`; it never transmits uploads externally. Quality
can derive requirement fulfilment but never transitions workflow state.

Milestone 8 adds pasted/exported WhatsApp-text ingestion, traceable parsing,
strictly catalogued FACT candidates, conflict detection, and explicit employee
review. Apply migration `0006_whatsapp_fact_extraction` and see
[WHATSAPP.md](WHATSAPP.md). Fact extraction is disabled by default and no live
WhatsApp or external AI integration is included.

Milestone 9A adds the typed canonical Canada application aggregate, service
invariants, review/provenance APIs, and employee maintenance UI. Apply migration
`0007_canada_application_model` and see [CANADA_APPLICATION.md](CANADA_APPLICATION.md).
It deliberately has no generator, legacy import, or workflow-transition
integration.

Milestone 9B adds an explicit preview/review/apply boundary for the existing
verified Google CSV parser, versioned Canada case files, and representative
profiles. Apply migration `0008_canada_legacy_import` and see
[CANADA_IMPORTS.md](CANADA_IMPORTS.md). Raw uploads are not retained and the
milestone does not generate forms, letters, or PDFs.

Milestone 9C adds canonical preparation readiness, structured blockers, an
immutable semantic payload, deterministic serialization/hash, and 138/138
audited projection coverage. See [CANADA_PREPARATION.md](CANADA_PREPARATION.md).
It does not generate PDFs, create preparation runs, or change the temporary
PREPARE-to-REVIEW transition gate.

Milestone 9D connects that payload to the existing Canada XFA writer through a
single adapter, persists versioned preparation runs and private generated
artifacts, derives current/stale/integrity state, and replaces the temporary
workflow gate. Apply migration `0009_canada_preparation_runs` and see
[CANADA_GENERATION.md](CANADA_GENERATION.md). No letter generator or external
submission is included.

Deployment Milestone D1 adds a synthetic-data-only Raspberry Pi 4 / Linux ARM64
staging Compose configuration, readiness diagnostics, persistent private
storage, and smoke/backup procedures. See [`../DEPLOYMENT_D1.md`](../DEPLOYMENT_D1.md).
It is not approved for real multi-user customer data and does not add
authentication.
