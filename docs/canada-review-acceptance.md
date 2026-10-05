# Canada review acceptance — 2026-10-01

This update implements the owner's three acceptance categories on top of the
existing canonical model, preparation, validator and transactional review.
It supersedes the earlier blanket requirement to manually answer all official
questions. It does not change Google Forms, publish code, or waive validation.

## Categories

- `necessary`: unresolved facts still need staff/client input.
- `can_be_automated`: a verified intake answer logically determines the official
  answer. These appear in the export's automatic-answer audit, not as open tasks.
- `badly_presented`: multiple technical checks belong to the same human task.
  The task retains every original issue and its severity; this category records
  why the checks were grouped, not permission to dismiss them.

## Restricted deterministic implications

Only `verified_20260929` uses these question contracts:

| Source | Official answer | What is deliberately not inferred |
| --- | --- | --- |
| Explicit Canada or other-country visa/entry refusal = Yes | Refusal/denied-entry/removal question = Yes | Two No answers do not resolve the broader removal question |
| Previously held a Canada visa = Yes | Previously applied to enter/remain Canada = Yes | No prior issued visa does not mean no prior application |
| Equivalent committed/arrested/charged/convicted question = Yes or No | Same explicit answer | Unknown text is not interpreted |
| Explicit post-secondary level, including incomplete university study | Ever had post-secondary education = Yes | A lower or unknown most-recent level does not prove No |
| No other-country residence for six months or more in the past five years | Narrower official more-than-six-months question = No | Yes does not resolve the threshold or excluded-country conditions |

No default No is introduced for medical, unauthorized-work/study, military or
security questions. No conclusion is inferred from merely visiting Canada or
from an overstay in an unspecified country. Unknown education labels still need
review. These are local template/intake mapping rules, not eligibility decisions.

Derived answers record `derived_rule` provenance with an `official-answer:`
source reference. Re-preparation recomputes them if the supporting fact changes.
Valid source-bound staff overrides, including an explicit blank, take priority.
A contradictory staff/source answer creates `OFFICIAL_SOURCE_CONFLICT` rather
than hiding the contradiction. Required medical, immigration, criminal or service
explanations create `OFFICIAL_DETAILS_MISSING`; a derived Yes does not manufacture
an explanation or clear a final-generation gate.

## Human tasks

The Required review tab shows collapsed task groups instead of a flat technical
list: applicant identity, address, activity timeline/countries, finances/evidence,
education, health, immigration, security, and separate family/history records.
Expand a task to inspect its individual checks. Technical details remain available.
The main application status reports task count first, with issue count as context.

**Open review task** presents the relevant canonical fields together. Conditional
explanations are shown beside their questions so staff can answer Yes and supply
details in one visit. Existing choices remain explicit Yes/No/blank selectors.
Financial amount and evidence reference are collected together. The activity task
offers one button confirming Brazil only for the listed missing countries; it
does not overwrite any existing country. Individual editing remains available.

Saving a task updates only the review draft. **Apply corrections (session)**
updates the loaded case, and **Save Canada case** persists it. Cancel retains the
loaded case. Task updates validate their field scope and current issue snapshot,
and roll back invalid updates atomically. Opening or grouping a task never clears
an error. Adding records and confirming residence proposals still use the existing
Corrections / Residence-travel controls.

Residence issues now use `RESIDENCE_RECORD_INCOMPLETE` and
`RESIDENCE_DATE_RANGE_INVALID`; travel issues retain their travel codes. The
previous misleading travel label for residence records is removed.

## Export and local verification

Draft reports now include `review_tasks` (member issues, category and status) and
`automated_answers` (field, value and source reference). The human checklist uses
the same task grouping. Reports remain private case artifacts. ERROR still blocks
all generation; blocking REVIEW still blocks the final-generation guard. The app
continues to generate reviewable drafts, not submission-ready applications.

Read-only checks on the supplied files, without copying their values into tests:

- Complete test CSV: **15 technical issues grouped into 8 tasks**, with 3 official
  answers derived (education Yes, previous residence No, criminal history No).
- Earlier CSV: **19 technical issues grouped into 9 tasks**, with 3 official Yes
  answers derived and missing explanations retained as required checks.

Source checksums remain unchanged. All added fixtures are constructed synthetic
cases. New tests cover positive/negative implication boundaries, unknown profiles,
changed source facts, override conflicts, missing explanations, grouped error
preservation, field-scoped atomic editing, save/reopen, grouped country confirmation,
report integration and the grouped finance dialog's apply/cancel behavior.

## Files

- `preparation.py`: narrowly scoped automatic official answers and provenance.
- `validation.py`: conditional details, source conflicts, correct residence codes.
- `review_tasks.py`: presentation grouping, relevant fields and automatic audit.
- `review.py`: atomic, scoped task updates on the existing review draft.
- `review_ui.py`, `compact_review.py`, `app.py`: grouped dialogs and task status.
- `pdf_drafts.py`: task-based checklist and machine-readable report.
- `test_canada_review_tasks.py`, `test_canada_review.py`: synthetic regression tests.

The new dialog is covered by mocked widget/callback tests. Native visual usability
acceptance with the caseworker remains separate; no fresh visual approval is claimed.
