# Automated intake (M12)

M12 places a durable intake boundary in front of the existing Canada CSV import pipeline. An authenticated `ADMIN` or `CASE_WORKER` can submit a Google Forms CSV without first opening a Case. The API stores the exact source bytes in private intake storage, records an `IntakeSubmission`, deduplicates it, resolves or creates a Case, and then delegates mapping and safe application to the existing import service.

## Internal boundary

The supported source type is `GOOGLE_FORMS_CSV`. `IntakeSourceAdapter` separates source parsing, identification, normalization, validation, and import creation from orchestration. M12 provides manual multipart upload at `POST /intake/submissions/google-forms-csv`; it does not expose a public webhook or include Google credentials. A future outbound poller, Sheets API client, Apps Script relay, or controlled connector can call the same internal service.

The Raspberry deployment remains reachable only through its configured private/Tailscale origin. Live Google acquisition is deferred.

## Identity and case resolution

Within a mapping version, a submission is unique by source type plus source hash. A non-null external submission ID is also unique by source type plus mapping version. Database constraints are authoritative under concurrent receipt; the losing receiver removes its redundant stored object and returns the existing submission.

Case resolution never uses names or fuzzy identity:

1. Reprocessing keeps the already linked Case.
2. An employee-selected Case is used after existence validation.
3. A unique Case previously linked to the same source type and external ID is reused.
4. Multiple historical links produce `NEEDS_REVIEW` and require employee selection.
5. Otherwise a new Case with the normal generated case number is created.

Applicant display names continue to derive from the Case's canonical applicant Person after safe import application.

## Processing and retry

Each processing run has an immutable attempt-history row. The orchestrator validates and parses before creating a new Case, invokes the existing preview/apply pipeline, auto-applies only `SAFE_NEW`, suppresses `SAME`, and counts unresolved new, conflict, ambiguous, or invalid candidates as work. Outcomes are `PROCESSED`, `NEEDS_REVIEW`, or `FAILED`, with safe employee-facing failure text.

Country values are normalized once while import candidates are built, based on the canonical target rather than the source field name. Raw provenance remains unchanged, while candidate values for canonical country fields use known ISO-3166 alpha-3 codes. The apply boundary independently rejects any non-canonical or unknown country value before an entity is created or flushed.

Receipt, attempt start, case resolution/import execution, and final outcome use separate durable transaction boundaries. This preserves a received source and attempt diagnostics if later processing fails. The existing import service retains its own transactional invariants for canonical mutations. Canonical confirmed information is never overwritten by safe mode.

Source parsing completes before automatic Case creation. Once a Case and import preview have been durably linked, a downstream apply failure intentionally retains that recovery Case and its review diagnostics. The failed queue item links to it, and retry reuses exactly that Case. Apply itself rolls back atomically, so no partial applicant/application batch remains and repeated failures do not create further Cases.

Failed or review-required submissions can be retried. A processed submission
whose mapping version predates the current mapping can also be reprocessed once
through the Intake queue. Reprocessing rereads the same immutable raw-source
reference, adds a processing attempt, and reuses the linked Case. It does not
create another submission or silently change the raw bytes.

Failures persist an employee-safe structured diagnostic on both the durable
submission and its processing attempt. Source-header failures, field validation,
database invariants, and unexpected persistence failures have distinct stable
codes. Import Apply diagnostics retain the affected section, field path, entity
ID when known, safe rejected value, correction guidance, and retryability; raw
database exceptions and stack traces are never returned.

The fingerprint-bound 234-column Google profile defines parent block 1 as the
father and parent block 2 as the mother. Older generic parent links are upgraded
only while reprocessing that preserved source after the current parser has
re-established those explicit roles. The existing Persons and relationships are
reused; names and gender are never used to infer parent type. Other accepted
Google profiles and `canada_case_json` remain generic unless their own source
mapping explicitly identifies a mother or father.

## Storage, operations, and security

`INTAKE_STORAGE_ROOT` points to private storage for raw intake sources. In Compose it is a third bind-mounted persistent directory at `/srv/visa-automatic/intake-storage`, separate from document and generated-artifact storage. Host preparation, preflight, backup, restore, ownership normalization, and repository ignore rules include it.

The Intake page shows operational counters and prioritizes `FAILED` and `NEEDS_REVIEW`. It exposes human-readable source, applicant, Case, status, issue count, retry, and Case navigation—not hashes, storage keys, canonical paths, or database diagnostics.

Counters are submission-oriented: Received counts durable submissions; Processed, Need review, and Failed reflect current submission status; Duplicates ignored sums duplicate receipts; New applications counts submissions that created a Case; Matched applications counts submissions resolved to a pre-existing Case and excludes any submission that created one. Reusing a submission's Case during retry increments neither resolution counter. Retry count and duplicate receipt count remain independent.

All endpoints use the M10 session, MFA, CSRF, and centralized authorization controls. Read and process permissions are granted only to `ADMIN` and `CASE_WORKER`; `REVIEWER` has neither. Receipt, duplicate suppression, successful processing, review-required outcomes, and failures write explicit audit events without raw content or secrets.
