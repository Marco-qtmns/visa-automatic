# Document quality and requirement completeness

Milestone 7 keeps four separate decisions: classification identifies a type and
owner; matching associates evidence with a requirement; document quality asks
whether one immutable upload is usable; requirement completeness asks whether
all accepted matched evidence collectively satisfies one requirement.

## Document quality

`DocumentQualityService` reads bytes only through `StorageProvider` and creates
a new immutable `DocumentQualityCheck` attempt for every explicit run. The
attempt records structured checks, concise observable evidence/issues,
evaluator provenance and version, SHA-256 document hash, safe extracted
metadata, and review audit fields. Prior attempts are retained.

General deterministic checks are limited to stored-file access, PDF decoding
with at least one page, and JPEG/PNG decoding. Parsing proves technical access,
not business acceptance. Type-specific profiles are strictly loaded from
`app/config/quality/document_quality.json` for all five catalog types.

The documented sources do not define reliable automated rules for passport
validity thresholds, required passport fields/pages/color, identity or
civil-status completeness, photo dimensions/composition, or a universal bank
statement period. Those checks remain `manual_review`. Bank statement text may
yield labelled account-holder and statement-period candidates; these are
evidence for employee confirmation, not automatic facts or legal conclusions.

The default `QUALITY_PROVIDER=manual_only` is local and conservative. Unknown
provider values fail closed to the same manual path. No upload or match invokes
an external provider and no full document text is logged or exposed. A future
visual provider must be explicitly configured and must preserve this interface
and privacy boundary.

Employees may rerun checks or explicitly accept/reject the latest attempt with
actor, reason, decision and timestamp. Manual acceptance produces the distinct
`manual_accepted` summary; it does not erase the automated findings.

## Requirement completeness

`RequirementCompletenessService` considers only currently matched, structurally
compatible documents whose final quality is `passed` or `manual_accepted`.
Every evaluation records matched and accepted IDs/counts, coverage, missing
items, explanation and trigger.

The default `single_document` policy completes when one compatible accepted
document exists. `month_coverage` requires an explicit, validated set of
`YYYY-MM` months. Coverage is the set union of confirmed metadata from the
latest quality attempt, never a file count: one PDF may cover several months,
while three copies for one month cover only that month. No current TRV rule
invents a month requirement.

Safe deterministic completeness may set `pending` to `fulfilled` with source
`automatic_document_evidence`. If qualifying evidence is rejected or unmatched,
only automatically derived fulfilment regresses to `pending`. Manual fulfilment
and waivers are preserved. All status changes have fulfillment-event history.
Reevaluation occurs after quality results/reviews, match add/remove, compatible
document metadata changes, completeness-policy changes, and reactivation.

Neither service changes workflow state. `WorkflowService` remains authoritative
and surfaces matched documents needing quality work before unresolved blocking
requirements.

## API and production limitations

The API exposes explicit quality run/history/accept/reject endpoints plus
completeness evaluation/history and fulfilment-event history. The employee UI
shows structured findings, reason-required manual actions, history, and matched
versus accepted versus fulfilled state.

Production hardening still requires authenticated authorization, malware
scanning, encrypted managed storage, retention controls, provider data-processing
review, observability without document contents, and operational concurrency
controls. These are deployment concerns, not fabricated document-quality rules.
