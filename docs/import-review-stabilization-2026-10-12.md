# Canada TRV import-review stabilization report

Date: 2026-10-12
Feature branch: `codex/import-review-stabilization`

## Reproduction scope and baseline

`CANADA_TURISMO_TESTE_COMPLETO.csv` is not present in this repository, so the
original customer import was not opened or reproduced. This work used only the
repository's synthetic `CanadaCase` objects and CSV fixtures. No production
data, uploads, dumps, exports, or generated customer documents were used.

Before the stabilization changes, the focused baseline was:

- Backend import/application/preparation tests: 61 passed.
- Frontend import/schema-review tests: 7 passed.
- Confirmed uncovered paths: negative additional citizenship was sent through
  country normalization; the other-passport answer targeted a nonexistent
  `TravelDocument.has_other_valid_passport` attribute; language intake fields
  had no import mappings; every section-confirmation field committed through a
  separate request; routine refresh selected the first unresolved section.

Representative synthetic traces used for regression tests:

| Source path / raw value | Proposed value | Canonical target | Initial state | Result |
| --- | --- | --- | --- | --- |
| `identity.nationality` / `Brazil`, `Brasil`, `Brasileira`, `BRA` | `BRA` | primary `PersonCitizenship.country_code` | new/same/conflict according to existing canonical data | Confirmable with ISO validation and recoverable target lookup |
| `identity.other_citizenship` / `Não`, `Nao`, `no` | `no` | `OfficialApplicationAnswer.answer` | new | No citizenship row is created |
| `identity.other_citizenship` / `Sim` | source preserved | additional citizenship country | ambiguous/missing | Employee must supply a country; no placeholder row is created |
| `passport.has_other_valid_passport` / `Não` | `no` | `OfficialApplicationAnswer.answer` | new | No secondary passport is created |
| `passport.other_passport_details` / explicit narrative | verbatim narrative | `OfficialExplanation.text` | explicit review | Details are preserved separately from the primary passport |
| `identity.languages` / `Português e inglês` | verbatim narrative | `OfficialExplanation.text` | explicit review | No native/preferred/service role is inferred |
| `trip.purpose` / Portuguese intake wording | verbatim intake wording | `TripPlan.intake_purpose_text` | reviewable | Official purpose is selected separately |

API behavior was exercised through service and route-level application tests.
Invalid country corrections return `IMPORT_FIELD_INVALID` details with section,
field path, rejected value, correction guidance, and rollback information.

## Root causes and repairs

1. Semantic yes/no answers were routed by field shape rather than question
   meaning. The importer now classifies additional-citizenship and
   other-passport answers before country/document handling
   (`backend/app/services/canada_imports.py:296-410`). Negative answers become
   canonical answers, yes-without-country remains missing/ambiguous, and
   details are preserved without placeholder documents.

2. An applied candidate created before target IDs were persisted could not be
   confirmed. Canonical target recovery now uses application identity,
   citizenship value, current residence, and stable import links
   (`backend/app/services/canada_imports.py:1155`).

3. Section confirmation called the single-field endpoint in a loop, so earlier
   commits could survive a later failure. `confirm_batch` now validates and
   commits one transaction, rolling the entire section back on error
   (`backend/app/services/canada_imports.py:742`; API route in
   `backend/app/api/canada_imports.py`).

4. Language fields existed in the verified intake and staff-review models but
   were absent from the 138 generator-input import mapping. Five supplemental,
   versioned import mappings were added without changing the audited 138-field
   invariant (`backend/app/config/canada_import_mapping.py:120-129`). Broad
   reported-language text is preserved; explicit native, preferred, and service
   fields remain distinct.

5. The review component selected the first unresolved field after every load.
   Initial/explicit-run selection is now separate from routine refresh
   (`frontend/src/components/CanadaImportSection.tsx:69-80`). Active section and
   review filter therefore survive confirmation and apply refreshes.

6. Candidate status and canonical review status were collapsed into a single
   confirmed/not-confirmed presentation. The UI now displays Confirmed,
   Corrected, Rejected, Applied, Needs confirmation, Conflict/Invalid, and
   Missing independently and reports separate dashboard counts
   (`frontend/src/components/CanadaImportSection.tsx:15-46,114-146`). Rejected
   proposals can be reconsidered and confirmed through the audited service.

7. The advanced trip editor accepted unexplained free text for IMM5257 purpose.
   The pinned repository template identifies itself as `.ENU-09-2023` and its
   XFA choice list supplies codes `01`, `02`, `04`, `05`, `06`, `07`, `03`,
   `08`, and `13`. The UI now shows the human labels and stores only those
   validated codes (`frontend/src/components/CanadaApplicationSection.tsx:10-15,166`;
   `backend/app/schemas/canada.py`). The original intake answer remains in
   `intake_purpose_text`.

8. Family records were rendered as one flat list. They are now grouped as
   parents, children, spouse/partner, former relationships, and other family,
   keyed by canonical relationship ID (`frontend/src/components/CanadaApplicationSection.tsx:136-162`).

9. The Next Action card allowed long text and its control to compete for the
   same layout space. Grid containment, wrapping, and bounded button styles
   prevent overlap at narrow widths (`frontend/src/app/globals.css:81-84`).

## Behavior and regression coverage

Added or expanded tests cover:

- Brazilian nationality normalization and applied-target recovery.
- Explicit no / yes-without-country / multiple additional citizenships.
- Primary passport confirmation, other-passport answer semantics, and detail
  preservation without a placeholder secondary passport.
- Rejection, reconsideration, correction, reapply, provenance state, and
  complete rollback after apply or section-confirm failure.
- Active-section preservation, accurate status badges/counts, atomic section
  confirmation, and rejected-value reconsideration.
- Reviewable language intake fields with no cross-field language inference.
- Stable family relationship display and separate family groupings.
- Verified IMM5257 purpose labels/codes and rejection of unsupported codes.
- Existing preparation, representative, authorization, deployment, document,
  workflow, and provenance suites.

Final verification commands and results:

- `PYTHONPATH=. .venv/bin/pytest -q backend/tests tests`: 480 passed after the
  new route was added to the authorization map (the initial full run exposed
  that missing classification; its focused test then passed 23/23).
- `npm test -- --run`: 69 passed across 14 files.
- `npm run build`: production compilation, TypeScript checking, and static page
  generation passed.

The component tests are the UI verification evidence for desktop-independent
navigation, field status, family grouping, purpose selection, and batch
confirmation. No authenticated browser screenshot was produced because this
checkout does not include test login credentials or a running seeded browser
environment.

## Schema and deployment

Migration `0017_import_review_state.py` adds the persisted
`canada_import_candidates.canonical_review_state` column. It must be applied
after migration `0016_canada_trv_schema_review.py`. This stabilization adds no
further database columns.

The import mapping version is now `m13-normalization-review-2`, so an identical
source can be previewed under the corrected semantic mapping without reusing an
older preview.

## Remaining limitations / explicit blocks

- The exact reported CSV remains unavailable; results are based on deterministic
  synthetic fixtures rather than a claim about that file's specific contents.
- Parsing warnings are collapsible, but legacy warning strings have no stable
  candidate identifier, so warnings cannot yet link reliably to a field without
  changing the persisted warning contract.
- Browser-level end-to-end screenshots remain blocked by the absence of a
  seeded authenticated runtime. Component interaction tests and the production
  build provide equivalent automated UI evidence for this checkout.
- This task did not create or push a remote pull request. Repository rules
  prohibit automatic push; the local review branch is
  `codex/import-review-stabilization`.

## Review and release notes

Do not merge without review. Review migration ordering, the pinned IMM5257
version, and any existing production rows containing legacy purpose labels
before deployment. Existing unsupported purpose values are shown explicitly as
legacy values in the editor rather than silently converted.
