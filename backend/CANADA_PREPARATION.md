# Canada preparation readiness and payload (Milestone 9C)

Milestone 9C defines Visa Automatic's internal preparation standard for the
currently supported Canada forms. It does not state or infer Canadian
immigration law. A legacy generator's ability to emit an incomplete draft is
not evidence that a canonical application is preparation-ready.

## Architecture and authority

`CanadaPreparationReadinessService` reads only the canonical M9A aggregate,
confirmed canonical FACTS, unresolved M9B conflict metadata, and existing
Requirement state. It does not read Google Forms, CSV files, `.canada-case.json`,
representative JSON, frontend state, or generator modules. Proposed/rejected
FACTS and unaccepted import candidates never supply values.

The version-controlled policy is
`app/config/canada_preparation_policy.py`, version `m9c-1`. Its rules classify
inputs as required values, required reviews, conditional values, collection
requirements, current-generator optional values, deterministic derivations, or
not applicable state. The policy and the complete projection can be inspected
through `GET /canada-preparation-policy`.

## Blockers, warnings, and review

The result uses constrained, employee-facing issues: `missing_value`,
`review_required`, `unresolved_import_conflict`, `unresolved_fact_conflict`,
`missing_selection`, `invalid_cardinality`, `inconsistent_data`,
`blocking_requirement`, `unsupported_value`, `missing_collection_record`,
`incomplete_collection`, and `ambiguous_reference`. Every issue contains a
semantic path, section, label, explanation, severity, and employee action.

Blocking issues prevent payload finalization. The schema also supports
non-blocking warnings, although the current policy emits only blockers.
Applicant-direct values are accepted where policy permits. Derived,
staff-reviewed, and narrative-derived passport fields require confirmation when
their active provenance remains unreviewed. Official `unknown` never means No;
official answers and triggered explanations require explicit review.

Unresolved preparation-relevant M9B conflicts and relevant FACT conflicts for
`sponsor.exists`, `host.exists`, and `trip.payer` block even when a current
canonical value exists. Active, blocking, pending Requirements block through
the existing Requirement/completeness lifecycle; fulfilled or waived records do
not.

## Conditional rules and explicit selections

- One applicant, primary citizenship, current residence, primary passport,
  primary email, and primary phone are selected explicitly.
- A separate mailing address is required only when it is explicitly different
  from the residential address.
- A primary host is required when confirmed `host.exists` is true; a primary
  host contradicts confirmed false.
- A primary funding source is required when `sponsor.exists` is true. Mixed
  self/sponsor state needs an explicit description instead of normalization.
- Primary education is required when the reviewed post-secondary answer is Yes.
- Existing approved explanation groups activate only when their configured
  official answer is Yes.
- Other names and another citizenship are optional for the current output path.
  Empty history/family collections are legitimate unless an explicit branch
  requires them.

## CanonicalPreparationPayload

`CanonicalPreparationPayloadBuilder` first requires a successful readiness
evaluation. It never inserts empty strings, “Not provided”, current dates, or
other placeholders. The frozen Pydantic value snapshot contains semantic
application, applicant/biography/citizenship/identifier, passport, contact,
address/residence, trip, host, funding, family, education, activity, residence
and travel history, official-answer/explanation, and immutable representative
revision data. It contains no live ORM objects, database IDs, import IDs,
storage keys, provenance history, unrelated timestamps, raw conversations, XFA
paths, or PDF encodings.

Payload schema version is `m9d-1` (the policy remains `m9c-1`). The M9D schema
adds structured valid secondary passports so the legacy other-passport
semantics can be reproduced without guessing. Collections use their canonical
`sort_order` where the model defines one; other selected collections have an
explicit semantic ordering. Dates and enums serialize through Pydantic JSON
mode. Canonical bytes use UTF-8 JSON with sorted keys, compact separators,
Unicode preserved, and non-finite numbers rejected. SHA-256 of those bytes is
the payload hash. Output-affecting data and generator-relevant ordering change
the hash; unrelated tasks, audit timestamps, and requirement history do not.

## Audited projection and privacy

The same policy module carries a version-controlled projection for all 138
audited legacy generator inputs. Each entry identifies its canonical source,
exact semantic payload selector, and whether it is a direct source or explicit
derivation. Automated tests enforce unique 138/138 coverage. The projection is
diagnostic preparation for M9D, not a generator adapter.

The general employee endpoint exposes only readiness diagnostics, versions,
counts, and a hash—not the full sensitive payload:

- `GET /cases/{case_id}/preparation-readiness`
- `POST /cases/{case_id}/preparation-readiness/evaluate` (read-only convenience)

Readiness evaluation itself remains read-only. M9D persists a `PreparationRun`
only when an employee explicitly requests generation. Authorization remains a
deployment requirement for all case APIs.

## M9D generation boundary

M9D consumes the payload only through a dedicated adapter and persists generated
forms as preparation artifacts. See [CANADA_GENERATION.md](CANADA_GENERATION.md)
for the mapping, lifecycle, workflow gate, storage, and platform audit. Legal
optionality beyond the approved project rules remains deliberately unspecified.
