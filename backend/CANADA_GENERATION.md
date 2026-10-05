# Canada form generation (Milestone 9D)

## Boundary and authority

The CASE-based path has one value input:

```text
canonical CASE -> readiness -> CanonicalPreparationPayload
  -> CanadaFormGeneratorAdapter -> legacy XFA writer
  -> StorageProvider -> PreparationRun / PreparationArtifact
```

`LegacyCanadaFormGeneratorAdapter` is the only backend integration that imports
legacy `CanadaCase` internals or `canada.pdf_drafts`. It translates the frozen
payload in memory, uses `TemporaryDirectory` for transient generator output,
and returns an explicit byte manifest. No `.canada-case.json` or representative
JSON is written. The new path does not call Google/CSV readers, `raw_response`,
M9B candidates, frontend state, or the legacy case store.

The adapter reuses the legacy dataclasses, mechanical XFA field writer,
template validation, output validation, and ReportLab continuation renderer.
It calls `generate_prepared_drafts`, which deliberately bypasses legacy
`prepare_case`, legacy source validation/readers, inferred answers, review-task
derivation, and legacy case persistence. Representation-only conversions are
allowed; readiness and canonical selection remain M9C responsibilities.

## Audited mapping and passport equivalence

`app/config/canada_form_adapter_mapping.py` contains the versioned `m9d-1`
mapping for all 138 audited inputs. Every row records canonical selector,
legacy destination, transformation, direct/derived supply mode, expected legacy
value, and consuming form. Import-time and automated-test assertions enforce
138 unique rows; `GET /canada-form-adapter-mapping` exposes the non-sensitive
specification.

The payload schema is `m9d-1`; the approved preparation policy remains
`m9c-1`. `has_other_valid_passport` now means that a non-primary passport owned
by the selected applicant remains valid on the official application date.
Expired documents, documents of another person, and the primary document do
not count. Readiness blocks ambiguous legacy details that cannot be represented
safely. The adapter only converts the resulting boolean to `Yes`/`No` and
passes the deterministic secondary-passport description.

## Manifest, lifecycle, and storage

Every successful run contains exactly:

- `IMM5257-DRAFT.pdf` (`imm5257`)
- `IMM5707-DRAFT.pdf` (`imm5707`)
- `IMM5476-DRAFT.pdf` (`imm5476`)
- `IMM5257-CONTINUATION-DRAFT.pdf` only when required

Continuation is required for more than three canonical activities, any
confirmed canonical residence history, any confirmed canonical travel history,
or the supported residential-address continuation condition. It is never
decided from Google data or a legacy narrative. No letter generator exists and
no letter artifact is created.

`CanadaPreparationService` checks readiness, builds and hashes the payload,
creates a running record, invokes the adapter, validates the exact manifest,
saves every PDF through `StorageProvider`, stores SHA-256 and provenance, and
then marks the run succeeded. A missing mandatory/conditional artifact, invalid
PDF, storage failure, changed in-flight payload, or adapter exception marks the
run failed with a constrained safe summary. Partial stored files are deleted
and cannot become current; earlier historical runs remain.

Artifact metadata stores adapter/generator versions, template identifier and
SHA-256, payload schema, policy, payload hash, and PDF SHA-256. Internal storage
keys are omitted from API schemas. Content is served through a controlled
streaming endpoint. `MAX_GENERATED_ARTIFACT_MB` bounds each generated file.

The database has a partial unique index allowing at most one `running` run per
case. Explicit repeated successful generation is allowed and preserved. The
latest successful complete run matching current payload/schema/policy is
current. Staleness is derived from the M9C payload hash; unrelated task/audit
changes do not alter it. Current status additionally reopens and hashes every
expected stored object, so missing or damaged files are integrity errors.

## Workflow behavior

`PREPARE -> REVIEW` requires a current, complete, integrity-checked package.
The old generated-DOCUMENT and `preparation_complete` TASK shortcuts are no
longer accepted. Generation itself never transitions workflow state.

When status evaluation finds a stale or invalid package in REVIEW or READY,
`WorkflowService` records a controlled regression to PREPARE, or DOCUMENTS when
an active unresolved blocking document requirement exists. SUBMITTED remains
terminal; a mismatch is surfaced as `submitted_discrepancy` and never reopens
or regenerates the case automatically.

## API and privacy

- `GET /cases/{case_id}/preparation`
- `POST /cases/{case_id}/prepare`
- `GET /cases/{case_id}/preparation-runs`
- `GET /preparation-runs/{run_id}`
- `GET /preparation-runs/{run_id}/artifacts`
- `GET /preparation-artifacts/{artifact_id}/content`

Ordinary responses never include the canonical payload or storage key. The
implementation does not log payloads, PDFs, passport numbers, addresses, or
financial values. Production authorization remains a later deployment concern;
M9D does not add authentication or external submission.

## Linux and ARM64 audit

The runtime path uses Python, `pathlib`, `tempfile`, `xml.etree.ElementTree`,
PyMuPDF, and ReportLab. It invokes no shell commands, AppleScript, GUI
automation, Adobe Acrobat, or desktop application. Repository-relative template
paths are resolved with `pathlib`; the permanent output root comes only from
`StorageProvider` configuration.

PyMuPDF documents official Linux 64-bit ARM wheels and the current PyPI release
publishes a `manylinux_2_28_aarch64` wheel. Therefore a Raspberry Pi 5 running
a 64-bit glibc-based Linux distribution new enough for that wheel is a supported
installation target in principle. This is not a hardware certification: CI on
Linux ARM64 and an on-device generation smoke test are still required before
production. Alpine/musl ARM64 is explicitly unsuitable for the official wheel,
and old glibc versions may require a controlled source build or newer OS.

XFA manipulation itself uses portable Python libraries. `os.chmod(0600)` is
portable as a call but provides POSIX permissions only; Windows privacy must
come from the configured private storage ACL. Temporary and persistent
directory writability must be verified by deployment health checks.

References: [PyMuPDF installation](https://pymupdf.readthedocs.io/en/latest/installation.html),
[PyMuPDF release files](https://pypi.org/project/pymupdf/).
