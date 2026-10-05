# Backend changelog

## Deployment D1.1 - Mac hardening and Raspberry preflight

- Added an authoritative tested deployment-environment contract, safe offline
  backend configuration validator, one-command Pi preflight, sanitized JSON
  result reporting, and a final acceptance evaluator.
- Hardened synthetic generation/persistence verification, Docker build-context
  exclusions, atomic manifest/hash backups, and separate-empty-target restore.
- Added static migration, dependency, ARM64, filesystem, network, logging, and
  public-repository audits for the Raspberry Pi 4 8 GB target.

No business rules or authentication were added. Docker and Raspberry results
remain unverified until the on-device sequence succeeds.

## Deployment D1 - Raspberry Pi development/staging packaging

- Added Debian/glibc Python 3.13 and Node 22 multi-stage container builds,
  PostgreSQL 17, Caddy one-origin routing, internal-only service networking,
  health checks, restart policies, and SSD/NVMe bind mounts.
- Added separate private document and generated-artifact storage roots with
  POSIX directory/file permissions and no static-file exposure.
- Added schema/storage/template/dependency readiness checks, a synthetic real
  M9D generator smoke fixture, ARM64 persistence script, and staging backup and
  documented restore procedures.
- Removed the deployed browser's localhost API dependency by using `/api` and
  documented Tailscale-only initial access, update flow, privacy, and the
  prominent lack of application authentication.

No business rules, authentication, users, external AI/submission, letter
generation, Tauri, installer, or production infrastructure were added. Docker
and Raspberry Pi execution remain unverified until performed on actual hardware.

## Milestone 9D - Canada form adapter and preparation artifacts

- Added a 138/138 versioned canonical-payload-to-legacy mapping and a single
  `LegacyCanadaFormGeneratorAdapter` boundary that performs in-memory
  representation conversion without Google, CSV, raw response, legacy JSON,
  frontend, or import-candidate reads.
- Reused only the mechanical tested XFA and continuation writers; the canonical
  path bypasses legacy preparation inference, fallback, review-task, and case
  persistence behavior.
- Added PreparationRun and dedicated PreparationArtifact persistence, private
  StorageProvider writes, exact manifest validation, per-PDF/template hashes,
  safe failure state, history, integrity checks, stale detection, and a
  database-backed one-running-run-per-case guard in migration `0009`.
- Replaced the temporary M2 PREPARE gate with a current canonical package gate,
  added audited REVIEW/READY regression and terminal SUBMITTED discrepancy
  behavior, and kept generation/transition explicitly separate.
- Added preparation/status/history/content APIs and employee generation,
  current/outdated/failed/history UI without letter or submission features.
- Added structured secondary-passport equivalence and documented Linux ARM64,
  XFA portability, storage permissions, privacy, and remaining deployment
  verification in `CANADA_GENERATION.md`.

No letter generation, external submission, authentication, Tauri, installer,
cloud infrastructure, AI reasoning, or new immigration rules were added.

## Milestone 9C - Preparation readiness and canonical payload

- Added versioned `m9c-1` preparation policy and inspectable 138-path semantic
  projection with automated 138/138 coverage.
- Added canonical-only readiness evaluation with structured employee blockers,
  review/provenance checks, M9B and FACT conflict checks, explicit selections,
  conditional branches, and existing Requirement integration.
- Added a frozen, typed `m9c-1` canonical preparation payload, stable UTF-8 JSON
  serialization, deterministic collection ordering, and SHA-256 hashing.
- Added readiness/policy APIs, PREPARE-specific backend Next Action guidance,
  and an employee readiness section without exposing the full payload.
- Added synthetic service, payload, hash, ordering, security-boundary, API, and
  frontend tests and documented the M9D adapter boundary.

No PDF/form/letter generator, Google or legacy fallback, PreparationRun,
generated artifact, automatic workflow transition, or Generate button was
added. The temporary M2 PREPARE gate is unchanged.

## Milestone 9B - Controlled legacy and Google intake import

- Reused the verified Google CSV, Canada case-file, and representative-profile
  readers behind server-side source adapters instead of duplicating parsing.
- Added a versioned, testable 138-path mapping with explicit source, transform,
  review, and conflict policies.
- Persisted import runs, field-level proposed changes, decisions, warnings, and
  stable source-to-canonical entity links in migration `0008`.
- Added exact-source idempotency, collection identity reuse, employee-order
  locks, confirmed-value protection, blank-value safety, FACT contradiction
  detection, transactional application, and field provenance.
- Added preview/review/apply APIs, safe batch acceptance, conflict resolution,
  backend Next Action integration, and an employee Import section.

No form/letter adapter, preparation payload/run, PDF generation, generation
integration, or workflow transition behavior was added.

## Milestone 9A - Canonical Canada application data

- Added a typed Canada application aggregate covering identity, citizenship,
  owned addresses, travel plans, funding, hosts, family, education, activities,
  residence/travel history, official answers, explanations, and representative
  authorization.
- Enforced explicit applicant selection, operational/family role separation,
  contextual address isolation, stable ordered identities, primary-record
  uniqueness, host XOR, and conservative unknown answers.
- Added immutable representative profile revisions and constrained field-level
  provenance that never replaces authoritative typed values.
- Added service-only writes, CRUD/review APIs, an aggregate bundle, employee
  maintenance UI, migration `0007_canada_application_model`, and synthetic
  invariant/API tests.

No generators, PDFs, legacy/Google imports, generation payloads, preparation
runs, or workflow transition changes were added.

## Milestone 8 - WhatsApp conversation fact review

- Added bounded pasted-text and `.txt` WhatsApp imports with deterministic
  iOS/Android parsing, multiline messages, parse warnings, and duplicate
  protection by case and content hash.
- Added an opt-in, provider-neutral extraction boundary constrained to the
  version-controlled `sponsor.exists`, `host.exists`, and `trip.payer` catalog.
- Persisted extraction runs and review candidates with confidence, evidence,
  source-message traceability, conflict links, and complete review history.
- Added explicit employee Accept/Correct/Reject decisions. Accepted or corrected
  values become confirmed WhatsApp facts and trigger requirement reevaluation,
  while prior conflicting facts remain auditable.
- Added a candidate-review Next Action, API routes, employee UI, migration
  `0006_whatsapp_fact_extraction`, privacy-safe configuration, and synthetic
  parser/service/API/frontend tests.

No person creation, document creation, automatic workflow transition, external
AI transmission by default, desktop packaging, installer, or Milestone 9 work
was added.

## Milestone 7 - Document quality and requirement completeness

- Added explicit, structured and historical document-quality evaluation through
  `StorageProvider`, including PDF/image integrity checks and SHA-256 provenance.
- Added strict configurable profiles for all catalog document types; unsupported
  content/visual judgments remain manual review rather than fabricated passes.
- Added auditable employee acceptance/rejection with required actor and reason.
- Added requirement completeness history, explicit single-document/month-union
  policies, accepted-evidence filtering, and duplicate-month protection.
- Added fulfilment provenance/events, safe automatic regression, waiver/manual
  preservation, service-layer reevaluation triggers, APIs and employee UI.
- Added migration `0005_document_quality_completeness` and synthetic tests.

No WhatsApp extraction, form/letter generation integration, workflow auto-
transition, external AI transmission, desktop packaging, or installer work was
added.

## Milestone 6 - Employee-reviewed document classification

- Added a vendor-neutral classifier boundary and replaceable content extractor.
- Added bounded embedded-PDF text extraction and provider-compatible image bytes.
- Added catalog-only type suggestions and conservative local person resolution.
- Added immutable classification attempts with confidence, concise evidence,
  provenance, document hash, failures, and employee review outcomes.
- Added explicit classify/history/accept/correct/reject endpoints and employee UI.
- Routed accepted/corrected metadata through Milestone 5 match safety.
- Kept provider configuration opt-in and preserved manual assignment on failure.

No quality approval, automatic matching/fulfilment, WhatsApp extraction,
generation integration, workflow automation, desktop packaging, or installer
work was added.

## Milestone 5 - Manual document upload and matching

- Added a configurable StorageProvider abstraction and safe local development
  storage using generated opaque keys.
- Added multipart PDF/JPEG/PNG upload with signature, MIME, catalog, ownership,
  and configurable size validation.
- Added controlled document retrieval without exposing internal storage paths.
- Added persisted many-to-many RequirementDocumentMatch records with foreign
  keys, indexes, and duplicate-pair protection.
- Added deterministic same-case, type, and owner compatibility validation,
  candidate listing, matching, unmatching, and history preservation.
- Rejected document metadata edits that would invalidate existing matches.
- Preserved manual fulfilment and backend workflow behavior; matching alone
  never fulfils a requirement.
- Added employee upload, assignment, download, match management, and matched-file
  displays without quality-approval claims.

No OCR, AI classification, owner inference, quality checks, WhatsApp handling,
generator integration, desktop packaging, or installer work was added.

## Milestone 4 - TRV requirement engine

- Added strict, version-controlled document catalogs and Canada TRV rules.
- Added deterministic evaluation from case data and confirmed facts with stable
  rule provenance and owner-role resolution.
- Added idempotent create, reactivate, deactivate, and unchanged lifecycle
  handling while preserving fulfilment and waiver state.
- Added automatic evaluation after relevant case, person, and fact mutations.
- Added an explicit reevaluation endpoint and employee UI action.
- Integrated active blockers with the existing Next Action behavior without
  automatic workflow-state changes.
- Added configuration, engine, lifecycle, API, workflow, and UI tests using
  synthetic records only.

No upload pipeline, document matching/classification, AI behavior, generator
integration, desktop packaging, installer, auto-update, or new migration was
added.

## Milestone 3 - Minimal employee UI

- Added a separate Next.js/React/TypeScript employee frontend for case listing,
  case creation, and complete manual case maintenance.
- Displayed the backend-provided Next Action and workflow transition history.
- Kept transition validation in the backend and submitted changes only through
  the transition endpoint with a configurable temporary actor.
- Added explicit, environment-configurable CORS support for the employee client.
- Added frontend component tests and a production-build verification path.
- Preserved the existing Tkinter form-filling application unchanged.

No upload pipeline, rules engine, automatic matching/classification, AI,
generator integration, desktop packaging, installer, or auto-update was added.

## Milestone 2 - Workflow state machine and Next Action

- Constrained CASE workflow state to `INTAKE`, `DOCUMENTS`, `PREPARE`, `REVIEW`,
  `READY`, and `SUBMITTED`.
- Added `WorkflowService` as the sole owner of transition maps, gates, audit
  history, and centralized Next Action decisions.
- Prevented direct workflow-state changes through case create/update APIs.
- Added persisted workflow transition history with actor, reason, and timestamp.
- Added manual requirement fulfilment states and auditable waivers.
- Added workflow, transition, and Next Action API routes.
- Added migration `0002_workflow_state_machine` and comprehensive synthetic
  state-machine tests.
- Documented generated-document metadata or a completed
  `preparation_complete` task as the temporary Milestone 2 preparation gate.

No employee UI, rules engine, document matching/quality logic, AI, generator
integration, installer, or deployment infrastructure was added.

## Milestone 1 - Core data model

- Added PostgreSQL-compatible persistence for Case, Person, Fact, Requirement,
  Document, and Task.
- Added Alembic migration `0001_core_data_model`.
- Added Pydantic request/response schemas, service-layer CRUD operations, and
  thin FastAPI routes.
- Added persistence, relationship, API, and complete-case reload tests.
- Kept the existing Google Forms, desktop review, PDF generation, and JSON case
  persistence code unchanged.
- Added public-repository-safe environment guidance and ignore rules; all test
  records are synthetic.

### Architecture deviation

The target backend is added under the existing program repository instead of
reorganizing the working desktop application. This preserves the current
launcher and generator paths while moving incrementally toward the documented
modular-monolith target.
