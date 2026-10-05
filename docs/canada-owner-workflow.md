# Canada intake: short client form, complete staff review

Current pipeline and review rules: [Canada TRV MVP](canada-trv-mvp.md). This update supersedes conflicting historical behavior below.

Update: the September 29 export is now verified. The reconciliation and remaining
manual checks are in [canada-20260929-reconciliation.md](canada-20260929-reconciliation.md).
The earlier export-pending statements below describe the previous implementation.

The owner's September 2026 decisions supersede earlier recommendations to add
more client questions or replace the live form. The live form has already been
edited by the owner. Its revised CSV has not yet been supplied, and no screenshot
was available in this task. The proposed headings in the agent YAML are examples,
not a verified transcription. Do not rebuild the form from that partial list or
remove its existing education, family, declaration or upload questions.

## Implemented behavior

* Explicit separate names, sex and birth-country aliases can be imported. Combined
  names are never split. Recognized revised headings are marked provisional.
* Explicit mother/father headings identify the respective parent. Historical
  Parent 1/2 or guardian/parent labels still need staff confirmation. Guardianship
  explanation and the court-document reference belong to separate staff fields.
* The client form keeps five children and five activity blocks. The review window
  allows staff to add any number of extra children or activities received through
  WhatsApp. This does not send, read or automate WhatsApp messages.
* Full addresses, including Brasília quadra/conjunto/bloco formats, remain intact.
  CEP is separate. Existing city/state answers are accepted, not required again.
  Country and mailing-address details can be confirmed internally when needed.
* Applicant and host contacts stay separate, including blank applicant contacts.
  Legacy repeated headings retain their section mapping. Unique draft headings
  are also supported; ambiguous mixed layouts fail with a review error.
* Activity state is imported inside its block. An ongoing answer and a blank end
  date remain distinct. Country is available for staff entry, never inferred from
  city/state. This implementation does not certify a gap-free ten-year timeline.
* A clearly labelled available-funds-in-CAD answer is stored as available funds.
  Historical estimated-spending answers retain their old meaning. No second
  financial question is required in the client form; payer information remains.
* Residence/travel narratives and declaration answers remain source text. Staff
  can review the narrative and record follow-up notes. Text is not automatically
  split into official immigration answers or individual trips.
* UCI, native/preferred/service language and guardianship are staff review fields.
  No additional client questions are required for them.

## What was missing about education?

The verified intake already collects education level, institution, course, dates
and country. Earlier recommendations referred to institution city/state and to
confirming whether the recorded course is the relevant post-secondary education
(the latest course is not necessarily the same thing). These are now internal
review fields. Keep the existing client section and clarify only when needed.

## Staff workflow

1. Choose Canada, load the CSV and review its source answers.
2. Edit missing facts explicitly. Use Add child / Add activity for WhatsApp
   exceptions. Use Add mother / Add father only if a parent record is missing;
   existing unresolved parent records can instead have their role confirmed.
3. Store guardianship explanations and a local document reference separately.
   Files are not uploaded, copied or attached automatically.
4. Check draft, then Apply corrections. Cancel discards edits and added records.
5. Choose **Save Canada case** in the main window. Save as `.canada-case.json`.
6. Reopen that file through Browse / Read client data. It preserves source headings,
   raw answers, confirmed facts, extra records and dated changes. Reimporting a CSV
   creates a fresh case; it does not merge saved corrections automatically.

Case files contain client data. They are excluded from Git and saved atomically
with owner-only file permissions. CSV/PDF source paths cannot be used as save
targets. There is no automatic save: save explicitly before closing the app.

## Verification boundary

The two previously verified 207-column schemas remain supported. Their current
coverage is 173 mapped columns / 34 unassigned columns; mapped narrative text
still needs review and does not imply official-form readiness. The source matrix
retains earlier audit snapshots and deterministic PDF target identities unchanged.

Revised-header support is exercised with synthetic data. Any other exact header
fingerprint triggers an unverified-schema notice. Before productive use of the
revised form, obtain its actual header-only/anonymized CSV and reconcile exact
labels, repeated sections and the fifth activity block against these aliases.
Do not require customers to rename or repeat already-completed answers.

Canada IMM5257 / IMM5707 / IMM5476 generation remains disabled. The saved case
format and intake validation do not implement official form generation or a
complete eligibility review.

Validation for this change: 91 automated tests pass, including old-schema
regressions, provisional header mappings, blank contacts, separate names, preserved
address/history text, staff additions, apply/cancel, save/reopen, invalid files and
atomic-save failure. The Australia PDF smoke test passes. The agent YAML parses
successfully. GUI commands are tested with mocks; interactive desktop appearance
has not been manually verified.
