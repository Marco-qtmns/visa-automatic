# Canada TRV pipeline and staff review (2026-09-30)

Review grouping and deterministic official answers: [Review acceptance update](canada-review-acceptance.md).

This document supersedes older intake/review restrictions in the historical
handoff documents. No Google Form changes or external publication are part of
this update. CSV files, official template files and existing case files are not
rewritten by the migration.

## Architecture retained

`source_readers.py` / `verified_intake.py` map ordered CSV cells into `CanadaCase`.
`preparation.py` enriches that case, `validation.py` emits typed issues,
`review.py` stores source-bound overrides, and `pdf_drafts.py` consumes the
prepared, validated case. The raw CSV is never used directly as a PDF mapping.

Existing public model names are retained: `identity` includes applicant and
current-residence facts, `contact.address` is the original complete address,
`trip` holds separate estimated spending and available CAD funds, and
`residence_records` / `travel_records` hold normalized history. Activity IDs,
status, description and original text, parent IDs/guardian status, application
date, legal guardian, estimated-spending currency and financial-source reference
extend these entities. There is no second competing case model.

## Import contract

The file importer accepts three exact, ordered header fingerprints: current
234-column `canada_trv_google_form_v1`, and the two previously verified 207-column
legacy/archive versions. Changing, reordering, removing or adding a header, or
changing row width, produces `CSV_SCHEMA_MISMATCH`. Repeated header values are
preserved as lists; the current mapping uses exact column positions. Low-level
`canada_case_from_csv_row` remains a compatibility adapter for historical schema
analysis/tests, not the public file-import boundary. Unverified adapter cases
are rejected by the generation validator.

The owner now explicitly defines the first parent block as father, the second
as mother, and the column after each surname as given names. These rules apply
only to the verified current profile. They replace the earlier conservative
interpretation of those labels. Old saved current-profile cases retain their
full-name source field while its value is copied without splitting into the
now-confirmed given-name field. Other schemas still require role clarification.

## Deterministic rules

- Guardianship is separate from parental role. At age 18 or above on the
  application date it is not required. Minors require father/mother/both/other.
  The explicit staff application date takes priority; otherwise CSV submission
  date is used, including Google's `YYYY/MM/DD ... GMT-3` format. Missing dates
  require review rather than assuming today's date or adulthood.
- Sex is never inferred. A known Brazilian birth state offers Brazil only as a
  suggestion. The address country requires staff confirmation; the address
  line and source answers retain their original whitespace and line breaks.
- Multiple missing activity countries produce one batch issue. Staff can
  confirm Brazil for the listed records or enter each country separately.
- Current employment is ongoing. Historical end dates before submission are
  completed; submission-day placeholders/missing end dates need review. Reversed
  dates are errors; future dates need correction/review. Changing an automatically
  classified period re-evaluates its status. Explicit staff status choices persist.
- A No answer to the residence question skips narrative parsing, including N/A.
  Yes activates parsing. The original text remains available even when skipped.
- Four-column travel records such as `Argentina - 2024-03-10 - 2024-03-20 - turismo`
  are accepted automatically when complete and date-valid. Explicit pipe/semicolon
  columns are also supported. Natural-language proposals still require review.
  Editing accepted records invalidates their content-bound acceptance.
- Known post-secondary levels require missing institution city/state internally.
  An unfamiliar education label is not interpreted as a degree: staff must answer
  the complete official post-secondary question.
- Estimated spending never supplies available CAD funds. Staff supply the amount
  and a financial source reference. Invalid/negative amounts are errors.

## Provenance, review and persistence

`provenance` maps model paths to value, source type/reference, confirmation and
source fingerprint. `overrides` stores staff entries and confirmations separately
from the original answers. Case serialization preserves both; missing new fields
default safely when loading older version-1 cases. Normalization and staff actions
operate on a review draft; Cancel leaves the loaded case unchanged.

Overrides reapply only to the same source fingerprint. Changed source produces
`STAFF_OVERRIDE_STALE`; the conservative MVP requires renewed review rather than
merging unrelated changed answers. Re-importing a CSV alone creates a new case:
reopen the saved `.canada-case.json` to continue corrections. There is no automatic
case matching across independent CSV imports, and saving remains explicit.

The **Required review** tab lists structured issues, shows source facts and
suggestions, and offers **Confirm suggestion** / **Enter / edit values**.
Batch confirmation asks whether all affected activities occurred in Brazil.
Choosing No opens individual country inputs. Composite records are edited under
Corrections, and residence proposals confirmed in Residence / travel proposals.
Official yes/no questions remain in the dedicated compact tab.

Issues deduplicate on code, entity type, entity ID and field. Existing string-list
APIs render these same objects; they no longer maintain separate validation rules.

## Issue codes

| Category | Codes |
| --- | --- |
| Import / source | `CSV_SCHEMA_MISMATCH`, `STAFF_OVERRIDE_STALE` |
| Applicant / address | `REQUIRED_FIELD_MISSING`, `APPLICANT_SEX_MISSING`, `BIRTH_COUNTRY_MISSING`, `BIRTH_DATE_INVALID`, `ADDRESS_COUNTRY_CONFIRMATION`, `APPLICATION_DATE_MISSING` |
| Family | `LEGAL_GUARDIAN_REQUIRED`, `PARENT_ROLE_MISSING`, `PARENT_ROLE_CONFLICT`, `FAMILY_NAME_INCOMPLETE`, `FAMILY_BIRTH_COUNTRY_MISSING`, `CHILDREN_CONFLICT` |
| Activities | `ACTIVITY_COUNTRIES_MISSING_BATCH`, `ACTIVITY_COUNTRY_MISSING`, `ACTIVITY_STATUS_CONFIRMATION`, `ACTIVITY_START_MISSING`, `ACTIVITY_END_MISSING`, `ACTIVITY_DATE_RANGE_INVALID`, `ACTIVITY_DATE_FUTURE`, `ACTIVITY_TIMELINE_GAP` |
| History | `TRAVEL_RECORD_INCOMPLETE`, `TRAVEL_DATE_RANGE_INVALID`, `HISTORY_CONFIRMATION` (history issue objects identify travel versus residence) |
| Education / finances | `EDUCATION_LOCATION_INCOMPLETE`, `AVAILABLE_FUNDS_CAD_MISSING`, `AVAILABLE_FUNDS_INVALID`, `FUNDS_SOURCE_MISSING` |
| Official questions | `OFFICIAL_ANSWER_MISSING` (one per unanswered official question) |

## Generation boundary

All exports run canonical preparation and structured validation first. Any ERROR
prevents even draft generation, before creating an output directory. REVIEW cases
can still produce explicitly incomplete drafts. A final-generation guard rejects
every blocking REVIEW as well. The application still exposes only draft generation;
it does not claim to produce signed, validated, submission-ready documents.

Draft reports include structured issues and validation status. Acrobat validation,
signatures, unsupported official mappings and template-version acceptance remain
separate work. This MVP validator is not a complete legal/eligibility determination.

## Local acceptance case (no response values reproduced)

The supplied 234-column CSV was imported read-only. The parent roles now resolve
without a question, complete explicit travel records are accepted, and activity
countries produce one batch issue. Remaining staff work includes applicant sex,
birth country, address country, one child's name components, a future-dated activity,
the activity timeline, one incomplete history record, available CAD funds and the
unanswered official questions. The original CSV's checksum is checked before/after.

The source education level is not a recognized post-secondary label; staff must
clarify the official education question before institution city/state can become
conditionally required. No financial figures or missing personal facts are guessed.

## Validation

`python -m unittest discover -s tests` and `python tests/smoke_test.py` cover the
pipeline and unchanged Australian workflow. New synthetic tests cover schema
rejection, parent contracts, adult/minor boundary, suggestions, raw address
preservation, batch/individual country resolution, status/date rules, source-bound
overrides and reopening, narrative parsing, deduplication and export blocking.
Historical tests were updated only where the new explicit requirements supersede
their prior expectations or where the review UI gained another widget.

## Verified result

After installation into the active project: **156 tests passed** (22 new pipeline
tests beyond the prior 134), the Australia smoke test passed, and `git diff --check`
reported no whitespace errors. The old file versions were preserved separately
under `Sicherungen/Vor-TRV-MVP-20260930`; nothing was uploaded or published.

The supplied case has **21 structured REVIEW issues and no ERROR issues**:
nine intake/history/activity/finance issues listed above, plus twelve unanswered
official questions. The unresolved child-name entry, future activity period,
history fragment, available funds and unfamiliar education level require human
clarification. Neither historical parent-role questions nor adult-guardianship
questions are emitted.

The native review window opened and closed cleanly with synthetic data. The
computer-use screenshot check timed out, so visual usability acceptance is still
outstanding; mocked UI and transaction regression tests passed.
