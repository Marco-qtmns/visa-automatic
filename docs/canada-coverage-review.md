# Canada schema and coverage review

Historical PDF-only audit. The actual CSV schema and current findings are in
[canada-csv-coverage-review.md](canada-csv-coverage-review.md). The primary coverage
matrix now uses actual CSV columns; its `pdf_schema_baseline` preserves this audit.

Inspected against repository baseline `1182768` on 2026-09-28. This phase produces
coverage evidence and an implementation plan, not generators or runtime reader changes.

## Evidence and limitations

The supplied `examples/canada/CANADÁ - TURISMO - GOOGLE FORMS.pdf` is a **blank printed
Google Forms schema**, not a completed submission. All 24 pages were text-inspected
and visually checked: 154 numbered questions, empty answer lines, unselected
choices, and no uploaded-file values. Example dates, dropdown options and helper
instructions are not client answers. Its SHA-256 is
`263ff59f7cadac2c1d743502f4a21ee48a160885dac88bb92a5afcc6dc98d70a`.
The original remains unchanged and untracked; no PDF is included in this change.

No separate live Google Form definition or Google Sheets export was supplied.
The PDF is the available source/schema evidence. Its main printed question titles
are transcribed in `tests/fixtures/canada_pdf_schema.json` with question/page IDs,
raw line breaks, required markers and significant separate instructions. CSV
projection headers join line wraps and remove required asterisks. Actual Sheets
headers, timestamp/email metadata columns, suffixes and instruction concatenation
remain unverified. PDF question index is explicitly NOT a CSV column index.

Calling the existing `read_google_forms_csv` on the PDF raises `UnicodeDecodeError`;
`CanadaWorkflow.read_source` rejects PDF input with its existing `ValueError`.
No PDF adapter was added. To exercise the reader honestly, the fixture projects the
154 printed labels into CSV columns and supplies only `SYNTHETIC_Q001` ...
`SYNTHETIC_Q154`. This is a schema-based experiment, not a real-client import test.

## Exact repeated-label findings

Occurrences are one-based within an exact normalized printed label.

| Label | Printed question IDs | Meaning/order |
| --- | --- | --- |
| Cidade | 38, 77, 84, 91, 98 | Applicant contact city, then activity blocks 1–4 |
| Telefone | 42, 57 | Applicant, then Canadian host |
| E-mail | 41, 58 | Applicant, then Canadian host |
| Tipo de atividade | 72, 79, 86, 93 | Four history blocks, newest first |
| Data de início | 73, 80, 87, 94 | Same four blocks |
| Data de término | 74, 81, 88, 95 | Same four blocks |
| Cargo | 75, 82, 89, 96 | Same four blocks |
| Nome da empresa, empregador ou instituição | 76, 83, 90, 97 | Same four blocks |
| Você possui outra atividade para informar nos últimos 10 anos? | 78, 85, 92, 99 | Next-block flags; final Yes has no fifth block |
| Extratos bancários dos últimos 3 meses | 137, 148 | Applicant documents, sponsor documents |
| Imposto de Renda | 138, 149 | Applicant, sponsor |
| Contracheques dos últimos 3 meses | 140, 150 | Applicant, sponsor |
| Contrato Social (se for empresário) | 142, 151 | Applicant, sponsor |
| Cartão CNPJ (se for empresário) | 143, 152 | Applicant, sponsor |
| 3 últimos pró-labores (se for empresário) | 144, 153 | Applicant, sponsor |

`Cidade de nascimento`, parent/ex-spouse birth cities, and `Cidade da
empresa/instituição` are different labels. There is no generic host Cidade field;
Q55 is the complete Canadian address and Q56 the host postal code.

## Reader result

The all-populated synthetic projection maps **79 of 154 question values** into
country-specific model fields. **75** have no domain assignment, although all
154 answers survive in `raw_response`, including duplicate-header values.

- 76 assignments showed no cross-column error in this experiment. These cover
  identity/language/residence scalar answers, passport/ID fields, applicant
  address/state/postcode, trip/payer/host details other than host phone/email,
  education/current employment, and all four six-field activity blocks.
  This verifies storage/column matching, not semantic completeness or official
  form validity. In particular, date normalization does not validate calendar dates.
- Three assignments are correct only while the applicant cell is nonempty:
  Q38 -> `contact.city`, Q41 -> `contact.email` (also `source_email`), and
  Q42 -> `contact.phone`. Blanking these cells imports Q77's activity city,
  Q58's host email and Q57's host phone respectively. Cause: `first()` skips
  blank values across repeated labels instead of binding an occurrence/role.
- Q57 and Q58 are unmapped despite existing `trip.host_phone` and
  `trip.host_email` fields. They can contaminate applicant fields instead.
- The remaining 73 questions lack corresponding semantic model fields:
  Q12; Q14–25; Q71/78/85/92/99; and Q100–154. These include previous residence
  details, spouse/history, history-control flags, family, travel/immigration,
  letter narratives, background incidents, uploads and declarations.
- Blank cells inside activity blocks retain relative column alignment. Entirely
  blank blocks are dropped from `activities`, so list indexes must not be used as
  permanent source question IDs. Q65–70 current employment is separate from the
  four history blocks; chronology, overlaps and gaps are not checked.

The matrix records the actual assignment and proposed target for every source
question. Its `covered` status means reader/model storage coverage only, never
permission to generate an official field without the stated transformations.

## Official-template verification

`canada/form_field_inventory.txt` regenerates byte-for-byte from the bundled PDFs.
It is a preliminary bare-name inventory, mixing template and auxiliary form packets.
The new read-only `tools/inventory_canada_fields.py` exports packet identities,
namespace-qualified hierarchical XML routes, named sibling paths and hashes.

| Template | SHA-256 | Observed structure |
| --- | --- | --- |
| IMM5257 | `0dc03b24e7914a178ad29e2cfae811045835a1d36d7a3c35f040251d0aca562e` | XFA; one visible signature widget; 284 template fields + 21 exclusion groups |
| IMM5707 | `6e59d35048ef3995e1d4583f08c38a710a351e23b1cc0fbfe517d82f38cb20ef` | XFA; zero widgets; 74 template fields + 6 exclusion groups |
| IMM5476 | `aca5c476b93d1c496b1afbc2cfe843499e852e31dcf0c192153bd01f8d6c56c4` | Hybrid XFA/AcroForm; 76 widgets; 76 template fields + 3 exclusion groups |

These are the supplied versions, not a claim of current IRCC publication status.
All 293 referenced nodes resolve uniquely against their packet and file hashes.
`IMM*_target` values reference `target_catalog` in `canada/coverage_matrix.yaml`.
Each entry contains packet name/index/hash, full XML route, full named hierarchy
and sibling index. The matrix uses JSON-compatible YAML 1.2 for dependency-free
parsing. No bare XFA name alone is a target.

Examples of important distinctions:

- IMM5476 `SectionA/office[0]` is applicant email, `[1]` is the no-email
  phone/address fallback, and `[2]` is application type. A bare `office` match is unsafe.
- IMM5707 has applicant, current spouse, Parent1, Parent2 and repeatable Child
  sections; it has **no sibling section**. Never put ex-spouse/sibling facts in
  current-spouse/child slots. Confirm parent role assignment explicitly.
- IMM5707 `COB` means country/territory of birth. Birth city/state is not equivalent.
  Its family names and given names are separate, including parents and children.
- IMM5257 has three fixed employment rows. Current employment plus four history
  blocks cannot be blindly zipped to them. Conditional candidate row mappings
  require chronology/overlap reconciliation and an overflow strategy.
- `Child[0]` is a template prototype, not an instruction to put every child into
  instance zero. Runtime binding/instances and Adobe behavior remain unverified.
- Some official group tooltips are stale. In particular, the previous-application
  and research-consent groups repeat unrelated text. Child captions/tooltips and
  hierarchy distinguish their actual meanings; no bare-name inference was used.

## Required changes: Google Form

The matrix's 42 `intake_gaps` entries enumerate exact target references. The main
changes are:

1. Add applicant passport family name, given names, sex, birth country, native-name
   representation; preserve combined full name without guessing its components.
   Collect separate alias components when applicable. Add service/native/preferred
   language and designated-language-test questions separately from Q26.
2. Collect country/status/from/to for repeatable previous residences, clarify
   citizenship/current-country exclusions and the six-month threshold, distinguish
   residence start from status start, and collect current status expiry/Other
   details. Add applying-country/equality and alternate status/date questions.
3. Correct relationship routing. Q13 sends single applicants to Q26 and divorced,
   separated/widowed applicants to Q18, bypassing the previous-relationship yes/no
   question. The previous-relationship section jumps back to Q14, risking a loop
   for a current spouse with previous history. Ask prior relationships for all
   relevant applicants, then proceed forward. Add current spouse DOB, birth
   country, address, occupation, marital status, accompanying status/native name;
   previous spouse separate name components; marriage-presence questions.
4. Give applicant and host contact questions distinct stable IDs/labels. Collect
   mailing/residential address roles and equality, structured unit/street/country/
   district, phone country/type/extension, and optional alternate/fax details.
   Do not assume a Brazilian state fits an official Canada/US province selector.
5. Add available funds **in CAD**, distinct from Q47 estimated expenditure. Add a
   second host if needed. Confirm purpose/Other details independently from the
   official application type; retain payer/host status/contact for letters.
6. Ask highest post-secondary education/ever attended (including apprenticeship),
   with institution city/state/country, rather than relying solely on most recent
   education. Collect country/state and ongoing status for every activity. Q70
   currently allows multiple employer states; change to a single location per
   period or explicitly model multiple locations. Replace the four-block cap with
   repeatable periods/continuation. Include study/unemployment and other gaps;
   retain ongoing status instead of instructing ongoing activities to end today.
7. Collect parent and child separate names, country of birth and marital status;
   child relationship and deceased details where applicable. Replace combined
   children/siblings narrative fields with structured repeatable entries; retain
   narratives as source evidence. Sibling facts support case history, not IMM5707.
8. Use separate, precisely scoped background questions: TB/contact within two years,
   health/social-service needs, Canada-specific overstay/unauthorized work/study,
   worldwide refusals and orders to leave, previous applications to enter/remain,
   criminal history, service history, violence-group association, ill-treatment/
   looting/desecration, and separate research-contact consent. Q118 (held a visa)
   and Q121 (visited Canada) do not answer ever applied. Q131 (overstay anywhere)
   does not answer all Canada-specific status violations. Attribute each incident's
   dates/country/circumstances/outcome/documents to its question instead of a shared
   undifferentiated Q132 narrative. Never infer negative answers from blanks.
9. Preserve Q122–127 intention-letter narratives explicitly: introduction,
   employment, reason for Canada, planned activities, first-degree family abroad,
   and return plans. Also retain Q43–58 trip/payer/host facts and Q67 job duties for
   support/invitation/funding letters; flag conflicts with structured answers.
10. Correct upload requiredness: the introduction says uploads are optional, but
    Q143/144 and Q152/153 are marked required. Keep applicant/sponsor uploads
    distinct, and store declaration choices separately from official signatures.

## Required changes: CanadaCase

Add domain components, independent of PDF names, with explicit unknown/no/not-
applicable distinctions and source provenance (question ID, occurrence, schema
version, raw answer, employee confirmation):

- Identity/residence/application additions listed above; known UCI/application
  number and confirmed application type/action. National ID issuing country,
  explicit has-document and structured additional passport/US-card details.
- `previous_residences[]`; `relationships.current` and `relationships.previous[]`.
- `family` with verified parent roles, children/siblings, separate names, birth
  countries, marital/accompanying/deceased details and raw narrative retention.
- Structured address/telephone objects; `trip.hosts[]`, available funds/currency
  and structured payer information; education location/highest-level details.
- Activity location/country/ongoing status plus source block IDs, continuation
  flags and validation of ten-year completeness; reconcile current employment.
- `travel_history.visits[]`, `immigration`, `background.incidents[]` and explicit
  scoped yes/no answers. Do not derive immigration answers from travel narratives.
- `support_letters`, applicant/sponsor `documents` references, and `consents`.

The matrix names proposed paths for each of the 73 missing source-model entries.
These are a design plan, not fields already implemented. Host phone/email already
exist and need reader assignments, not duplicate model fields.

## Required changes: source_readers.py

1. Introduce a versioned schema/semantic role binding. Prefer stable question IDs;
   use exact label + occurrence only for a recognized complete header layout.
   Reject/review unknown duplicate layouts instead of guessing. Do not claim PDF
   question offsets are real CSV offsets.
2. Preserve blank applicant occurrences. Bind Q38/Q41/Q42 to applicant and
   Q57/Q58 to host; never fall through to another person's nonempty answer.
3. Keep all repeated activity cells aligned, carry source block IDs and flags,
   detect overflow, and separately reconcile current employment. Add structured
   assignments for the new model components once the intake is revised/verified.
4. Keep `raw_response` and unknown headers; preserve source order and original
   labels as well as normalized keys. Validate full dates and known enum values;
   do not treat N/A, a blank, No and unknown as interchangeable.
5. Do not split combined names, family-member lists, immigration events or address
   narratives heuristically. Route them to correction/review. A future PDF importer
   needs a separate reader and populated examples; it must reject blank schemas
   and distinguish printed examples/options from actual selected answers.

## Required changes: correction/review UI

Canada review is currently read-only. Add editable country-specific sections for
identity/name components, spouses/parents/children, residence/activity/travel
periods, host/payer, background incidents and letter narratives. Show source
question/occurrence beside values and distinguish missing, ambiguous, skipped and
confirmed answers. Present contact-role conflicts, time gaps/overlaps/overflow,
non-equivalent questions and original narrative for employee resolution. Collect
missing facts explicitly and save reviewed values without overwriting source
answers. Keep generation unavailable until future mapping/validation work is
complete; consent is never a signature.

## Required changes: representative settings

Create separate Canada settings for representative names, firm, full structured
address, phone/fax/email, compensation category, professional classification,
province/registration/membership and supervising lawyer when applicable. Values
must be explicitly supplied and verified; never copy Australia recipient settings
or Canadian-host contact values. Keep appointment/update/cancel/withdraw action,
previous representative details, applicant UCI/application number/type and dates
in case-specific review. IMM5476 section branches and all signatures/signing dates
remain manual; no credentials or authorization are assumed.

## Tests and stopping point

Baseline: 21 existing unit tests passed. The expanded suite runs 37 tests:
**33 pass and four expected failures** documenting the existing reader defects.
Expected failures are intentional future-facing regression cases, not silently
fixed or skipped: blank applicant city/email/phone isolation and host assignment.
Other tests cover the complete 154-question schema, duplicate/activity ordering,
blank activity blocks, raw retention, unguessed names/sex, mapping counts, exact
hashed XML target resolution and duplicate `office` indexes. Fixtures contain
only source labels and generated markers; no client values, attachments or URLs.

Run with the project's Python environment:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke_test.py
python tools/inventory_canada_fields.py --output /tmp/canada-inventory.json
```

Australia smoke generation and its field assertions pass. No Canada form was
filled, flattened or signed. No model, parser, correction UI or representative
settings implementation is included; those are the next planned phase.
