# Canada editable PDF drafts

Review grouping and deterministic official answers: [Review acceptance update](canada-review-acceptance.md).

Current pipeline and review rules: [Canada TRV MVP](canada-trv-mvp.md). This update supersedes conflicting historical behavior below.

The Canada panel now creates IMM5257, IMM5707 and IMM5476 XFA drafts from the
supplied templates. This is a partial, explicitly reviewable export, not a
submission-ready or fully automatic application. No real client values appear
in tests or this document.

## Workflow

1. Load the Canada CSV or saved `.canada-case.json`.
   New CSV cases receive a conservative preparation pass. Saved cases can be
   prepared in the review draft; Cancel leaves the loaded case unchanged.
2. Review the intake. The internal `Representative` group holds Canada-specific
   names and contact details; it never reuses an Australian recipient or host.
   Select the explicit action (appointment, contact update, cancellation,
   replacement or withdrawal) and paid/unpaid category from the lists. Enter
   membership details only as confirmed. Cancellation uses separate former
   representative names; a withdrawal fills section D, not section B.
   **Save Canada representative profile** stores reusable details in a separate
   local `.canada-representative.json`. **Load Canada representative profile**
   applies those details with an audit trail. Neither action/cancellation choices
   nor old representative names are exported in the reusable profile.
   **Canada representative settings (remember)** opens a one-time settings
   dialog without requiring a loaded case. Its private default profile lives in
   the application's local settings directory and automatically fills an empty
   representative block when a case is loaded. Existing representative details
   are never mixed with a different default profile.
3. In `Official Review`, staff can enter address components and answers to the
   complete official background questions. Keep these blank when unconfirmed;
   broad intake narratives are never converted to official yes/no answers.
   The first **Official questions** tab presents missing facts and complete
   background questions with explicit Yes/No/blank choices. Detailed address
   fields remain under **Corrections**. **Residence / travel proposals** shows
   proposed records beside original text. Edit, add/split or remove records,
   then confirm each one. Edits invalidate confirmation. Missing country/status
   or invalid/reversed periods prevent confirmation. Removed proposals are not
   silently regenerated on reopen.
4. Save the case, then choose **Create Canada PDF drafts**. Select a parent
   folder; the app creates a new timestamped directory without overwriting files.
5. Read `review-checklist.md` and open the PDFs in desktop Adobe Acrobat. Complete
   remaining fields, review the generated continuation sheet, validate where available, then
   arrange the appropriate signatures separately.

The bundle contains all three PDFs, a complete saved case, a human-readable
checklist and `review-report.json`. The machine-readable report records the
template hash, dataset packet index/hash, hierarchical dataset path (explicit
1-based sibling index where repeated), output hash and source model path for
each write. Values remain in the private case/PDF, not in the mapping report.

CLI alternative: `python -m canada.pdf_drafts --case CASE.canada-case.json
--output NEW_DIRECTORY` (one command).

## Implemented and intentionally open

- Explicit passport names and supported dates, passport number, selected coded
  country/language/sex/purpose choices, email, host, available CAD funds,
  education details and the first three activity rows can be transferred.
- Owner-confirmed child-name handling applies only to the verified schema:
  retain the explicit surname and remove an exact surname prefix or suffix from the full
  child name. Already separate given names are accepted; partial overlaps need
  review. Parent full names still require confirmed given names. Spouse Other
  text becomes the separate address; explicit Yes uses the applicant address,
  while bare No remains unresolved. Staff corrections take precedence.
- A small explicit dictionary translates supported Portuguese dropdown labels
  (for example Brasil, Brasileiro, Solteiro, Turismo). Unknown labels need review.
  IMM5257's own scripts reject some Portuguese accents. The export retains
  French accents and normalizes other decomposable Latin accents (Brasília to
  Brasilia), recording a transformation in the write report. Source/case values
  stay unchanged. Unsupported characters require a reviewed spelling.
- Official choice labels or stored codes must match the pinned template. A
  unique passport-list label such as `BRA (Brazil)` also accepts `Brazil`.
  Portuguese free text that is not an exact option remains for review; unknown
  country, sex or immigration facts are never inferred.
- Brasília addresses remain intact in the source. Staff can supply the official
  address components internally without adding client questions. Brazilian
  state codes are not inserted into Canadian province dropdowns.
- IMM5707 supports more than five children through repeated XFA dataset nodes.
  Repeated PersonalData groups are indexed separately. The actual pinned form
  labels both parents **PARENT 1/2 (MOTHER OR FATHER)**. Preserve source order;
  do not infer parental role or substitute legal guardians. Older intake role
  warnings remain for staff reconciliation.
- IMM5257 has three activity rows. Current employment joins history once, with
  stable source provenance. Active periods come first, then most recent starts.
  Additional records appear in `IMM5257-CONTINUATION-DRAFT.pdf`, with review
  markers for unresolved fields. Month dates are supported without inventing
  days. A historical end date before CSV submission establishes a finished
  period; a submission-day placeholder stays unresolved. Timeline gaps and
  invalid dates are reported. Review current employment in the activity record.
- Confirmed residence records fill two official rows when the complete
  six-month question is confirmed Yes. All confirmed residence/travel records
  also appear in the supplement. Full-date targets require actual days; month
  dates stay in the supplement. Parsing supports delimited records and common
  Portuguese/English phrases. Unfamiliar prose stays as a partial proposal for
  staff completion; the entire original remains visible.
- Unsupported marital/family choice translations, phone formatting and
  mailing-address copying still require completion in
  Acrobat. Representative actions and all eight paid/unpaid category choices
  can be set internally; their professional details must be confirmed by staff.
- Staff-entered official background answers are exported separately from the
  broader source history questions. The source data and original consent remain
  unchanged. No consent, signature, signed date, validation flag or barcode is
  generated.

## Verification and limits

The writer checks each source template's full SHA256 against the coverage
matrix, writes only the datasets packet using an incremental save, and reopens
every output to verify its values. All other XFA packets remain byte-identical.
The template's own calculation scripts are preserved and can affect visible
fields; desktop Acrobat visual review is therefore essential. Browser viewers,
Preview and ordinary PyMuPDF rendering show a fallback page, not the XFA form.

Tests cover repeated children/parents, missing facts, invalid dates/codes, funds
vs costs, applicant/host/representative separation, untouched signatures and
packets, changed templates, overflow, transactional failure, old case migration
and UI routing. Use the full unittest suite and Australia smoke test before
release. An executable release build and a complete production acceptance test
are separate from these source-level checks.
