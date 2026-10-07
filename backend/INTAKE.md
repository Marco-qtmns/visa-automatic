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

Receipt, attempt start, case resolution/import execution, and final outcome use separate durable transaction boundaries. This preserves a received source and attempt diagnostics if later processing fails. The existing import service retains its own transactional invariants for canonical mutations. Canonical confirmed information is never overwritten by safe mode.

Only failed or review-required submissions can be retried. A retry rereads the same immutable raw-source reference, adds a processing attempt, and reuses the linked or employee-selected Case. It does not create another submission or silently change the raw bytes.

## Storage, operations, and security

`INTAKE_STORAGE_ROOT` points to private storage for raw intake sources. In Compose it is a third bind-mounted persistent directory at `/srv/visa-automatic/intake-storage`, separate from document and generated-artifact storage. Host preparation, preflight, backup, restore, ownership normalization, and repository ignore rules include it.

The Intake page shows operational counters and prioritizes `FAILED` and `NEEDS_REVIEW`. It exposes human-readable source, applicant, Case, status, issue count, retry, and Case navigation—not hashes, storage keys, canonical paths, or database diagnostics.

All endpoints use the M10 session, MFA, CSRF, and centralized authorization controls. Read and process permissions are granted only to `ADMIN` and `CASE_WORKER`; `REVIEWER` has neither. Receipt, duplicate suppression, successful processing, review-required outcomes, and failures write explicit audit events without raw content or secrets.
