# Controlled Canada legacy import (Milestone 9B)

Milestone 9B moves values from the tested legacy intake boundary into the
canonical Canada application. It does not generate forms, letters, continuation
pages, or PDFs and does not change workflow state.

## Architecture and adapters

Uploads are server-side and bounded. `VerifiedGoogleImportAdapter` calls the
existing verified CSV parser, including its header-fingerprint and duplicate
column checks. `CanadaCaseImportAdapter` calls the existing versioned
`.canada-case.json` loader. Both produce a legacy `CanadaCase`, which is then
mapped by one canonical import service. `RepresentativeProfileImportAdapter`
uses the existing validated representative-profile loader.

The canonical domain never interprets Google column positions, CSV headers, or
the case-file wire format. The uploaded bytes are used only while parsing; the
database keeps a SHA-256 digest, a basename-only source identifier, candidates,
decisions, and provenance, not the raw customer source.

## Versioned mapping and source classifications

`backend/app/config/canada_import_mapping.py` is the inspectable `m9b-1`
mapping for all 138 audited generator input paths. Each entry declares its
canonical target, transformation, source classification, review policy, and
conflict policy. The classifications are:

- `applicant_direct`: structured applicant input, eligible for the safe batch;
- `legacy_staff_review`: prior staff/application answers, requiring explicit review;
- `legacy_derived`: a legacy deterministic preparation result, never promoted to confirmed;
- `representative_profile`: reusable representative master data;
- `legacy_narrative_derived`: a structured proposal originating in narrative text.

Blank source values create no candidate and cannot erase canonical data.
Unknown official answers remain `unknown`; they are never converted to `no`.
Free-text trip purpose maps only to `TripPlan.intake_purpose_text`, never to an
IMM5257 purpose code.

## Import lifecycle and conflict rules

1. A preview parses the source and persists a `CanadaLegacyImportRun` plus
   field-level `CanadaImportCandidate` rows.
2. Employees inspect new, same, conflict, and ambiguous candidates grouped by
   domain section.
3. They may accept/reject individual candidates, resolve each conflict, or
   accept all safe, non-conflicting direct applicant values.
4. Applying accepted candidates is one transaction. A failed invariant rolls
   back the entire batch.
5. Applied values receive `FieldProvenanceReview` rows with source reference
   and source digest. Unambiguous `applicant_direct` fields covered by the
   documented `safe_direct_batch` policy are automatically `confirmed`.
   Conflicts, classifications, official answers, and other explicit-review
   fields remain `unreviewed` until the employee confirms the canonical value.

The safe batch excludes conflicts, ambiguous host/person mapping, official
answers, representative selection, and every field whose mapping requires
explicit review. A different import never overwrites an active confirmed or
corrected provenance value. Same values do not conflict and do not create a
second typed record.

## Identity, ordering, and idempotency

The selected canonical applicant is always reused; name-only person matching is
never performed. `LegacyImportEntityLink` binds stable source block keys (for
example `child:legacy:1` or `activity:csv:2`) to canonical UUIDs. Parent, child,
activity, residence-history, and travel-history reimports therefore update the
linked entity instead of appending duplicates. Exact-source idempotency uses
case ID, source type, source SHA-256, and mapping version.

Legacy order initializes `sort_order`. A manual canonical reorder marks linked
rows `employee_order_locked`; later imports retain that employee ordering.
Ambiguous hosts remain review items because the importer does not guess person
versus organization from a name.

Country input is normalized by the single country-normalization service before
candidate validation. It accepts ISO alpha-3, ISO alpha-2, English names,
Portuguese names and supported Portuguese nationality adjectives. Multiple
citizenships separated explicitly in the source become separate candidates and
canonical citizenship rows. Unknown values remain attached to their raw source
and become field-specific invalid review items; the Apply boundary independently
requires a real ISO alpha-3 value.

All address contexts use the same conservative address normalizer. The original
text is retained, reliable components are populated without overwriting
structured CSV components, unresolved fragments remain in review diagnostics,
and the canonical address stays `needs_review` until employee confirmation.

Apply errors use the application error contract: category, stable code, section,
canonical/source field path, stable entity ID when available, safe rejected
value, correction guidance, and retryability. Candidate-level errors identify
the exact field while the surrounding transaction still rolls back atomically.

Representative imports create reusable profiles and immutable revisions.
Changed source data creates a revision; importing a default profile never
creates a case authorization. Authorization remains a separate explicit action.

Confirmed `host.exists=false` or `sponsor.exists=false` FACTS that contradict
structured host/funding proposals produce conflicts. Neither representation is
silently rewritten. Unresolved import conflicts surface as
`REVIEW_CANADA_IMPORT` through backend Next Action.

## API and manual fallback

- `POST /cases/{case_id}/canada-imports/preview`
- `POST /cases/{case_id}/canada-imports`
- `GET /cases/{case_id}/canada-imports`
- `GET /canada-imports/{import_id}` and `/changes`
- `POST /canada-imports/{import_id}/apply`
- `POST /canada-import-changes/{id}/accept`, `/reject`, and `/resolve`
- `GET /canada-import-mapping`

When a legacy value cannot be transformed safely, the preview retains it as a
reviewable proposal and emits a warning. Employees can reject it and use the
normal typed Canada application forms. Existing legacy parsing remains a
dependency until M9C generation equivalence is separately implemented and
verified. No production source files or real customer fixtures belong in the
public repository.
