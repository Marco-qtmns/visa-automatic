## September 29 export reconciliation (current)

The newly supplied 234-column export and all 42 screenshot pages have now been
reviewed. See [canada-20260929-reconciliation.md](canada-20260929-reconciliation.md).
233 domain columns are mapped; timestamp remains in raw source metadata. Exact
schema identity guards the duplicate/mislabelled parent-country question. Missing
facts and ambiguous names still require review; PDF generation remains disabled.

## Owner workflow adaptation (historical)

See [canada-owner-workflow.md](canada-owner-workflow.md) for the current behavior.
Staff can add WhatsApp follow-ups, keep guardianship separate, confirm countries,
UCI and languages internally, and save/reopen complete `.canada-case.json` files.
Current verified-schema coverage is **173 mapped / 34 unassigned columns**.
The revised live export is still pending; proposed aliases are explicitly provisional.
Earlier session-only and question-expansion recommendations below are historical.

## Manual correction editor (historical)

Canada review now offers editable fields, original answers, draft validation and an
applied-change log. Select a field or expand a source block, edit its value, then
choose **Apply corrections (session)**. **Check draft** updates issues without
changing the case. **Cancel** and closing the window discard the draft. Reopening
the review keeps previously applied corrections and shows their history.

Corrections are kept **only in the current application session**. Reimporting the
CSV or exiting the app discards them; no source files are changed. Durable case
save/load is still a separate development step.

Separate names and birth countries can be entered explicitly for the applicant
and family members. Parent roles use a manual selection; source parent/guardian
labels and source block indexes remain read-only. Former spouse name components
and current/former spouse birth countries now have manual fields. No values are
inferred. Each applied change records its path, old/new value and UTC timestamp.
Conflicting review sessions cannot overwrite newer edits. Original source answers
remain untouched. Review validation is incomplete and is not official form readiness.

Automatic intake coverage remains **157 / 207** columns. Canada PDF generation
remains disabled. Tests cover apply, cancel, active-field saving, history, source
protection, conflicts, validation and GUI routing without opening desktop windows.
Validation: 71 unit/regression tests and the Australia PDF smoke test pass.
Interactive desktop appearance has not been manually verified.

## Family intake implementation (current)

The Canada model and CSV reader now preserve current/former relationship answers,
two parent/guardian source blocks, and five child source blocks. Both verified
CSV variants are supported, including mixed child labels in the latest export.
Current coverage is **157 mapped / 50 unmapped source columns**. The historical
findings below describe the earlier audit and must not be read as current defects.

New fields live in `CanadaCase.relationships` and `CanadaCase.family`; exact
aliases are maintained in `canada/family_schema.py`. Block membership uses headers,
not absolute CSV offsets. Empty blocks keep their source index. Duplicate fields
inside a block and recognized fields without a valid block are rejected. Dates,
yes/no answers, co-residence answers, combined names and death narratives remain
source text; the importer infers no mother/father role, birth country, name split
or applicant address. Contradictory child declarations are flagged for review.

The Canada review window displays all relationship and family fields, including
source block and role. It remains read-only. Existing official PDF target references
and template identities remain unchanged; importing data does not authorize an
automatic official form mapping. Canada PDF generation remains disabled.

Remaining work: editable correction/review with explicit parent roles, structured
names and birth countries; outstanding immigration/travel and letter-question
fields; representative settings. Intake changes must collect those missing facts.
No source client files or filled values are included. Regression tests use only
synthetic data. The full suite has 61 tests, plus the Australia PDF smoke test.

# Canada coverage verified against the actual CSV

**Implementation update:** The six import defects described below are now fixed.
The reader supports both verified date/education header variants, preserves blank
applicant contacts/city, assigns host contacts by section, and rejects ambiguous
duplicate layouts. The current matrix records 81 mapped / 126 unmapped columns;
`reader_audit_before_import_fixes` preserves the original audit. All former
expected failures are regular passing regression tests. Validation: all 54 tests
and the Australia smoke test pass. Both real exports were also checked without
storing their response values; the four formerly unassigned fields now match
their source answers. The remaining sections
describe the historical findings and the still-pending wider Canada work.

This report supersedes the schema assumptions in `canada-coverage-review.md`.
The earlier PDF audit remains historical evidence in that report and in
`coverage_matrix.yaml` under `pdf_schema_baseline`. Runtime reader/model changes
and Canada generation remain outside this audit phase.

## Source and privacy

The latest standalone `CANADÁ - TURISMO.csv` and the earlier archive each contain
**207 columns and one response**: a timestamp plus 206 intake columns. Both
exports have width 207, but **63 header positions differ and the response values
also differ**. The latest standalone file is primary; the archive is a separate
baseline. Values are never merged. Both source files are read-only; neither was
copied into the repository or committed. The real reader experiment used a
private temporary directory, removed automatically. No client values, file URLs,
contact values or names appear in committed fixtures or this report.

- Archive SHA-256: `4f64d39119e7975abacff62faf3e1ab6691a36267d9a0ba14268a677cf2135cc`
- Latest standalone CSV SHA-256: `2612e4e71e63712ad1d2d7e179f9857052b20db1e0d7cfae6d50a1647d487d3f`
- Archived CSV SHA-256: `d8fd4d70af4e765848206992505ae3a33550565393a792d2f4f638ffdbb36f76`
- `tests/fixtures/canada_csv_schema.json` records only exact headers, occurrences,
  indexes and provenance hashes.
- `tests/fixtures/canada_csv_synthetic.csv` uses those exact headers and generated
  `SYNTHETIC_C000` through `SYNTHETIC_C206` markers, never response values.
- Separate `canada_archive_csv_schema.json` and `canada_archive_csv_synthetic.csv`
  fixtures preserve the earlier header layout without its response values.
  Narrow `.gitattributes` rules allow intentional whitespace inside these two
  CSV fixtures; tests verify it against the exact header fingerprints.

In this report and the current matrix, **Cxxx is the zero-based CSV column index**.
C000 is timestamp. Historical Qxxx identifiers refer to printed PDF questions;
they must not be used as current CSV column numbers.

## Schema differences from the PDF

| Current CSV columns | Verified change | Effect on prior plan |
| --- | --- | --- |
| C011 | `Desde quando reside nesse país atual? ` | Existing residence-start exact-match header is stale. |
| C013 | Explicit `status migratório` in prior-residence narrative | Still needs structured model/reader handling. |
| C008, C018–019 | Current spouse DOB, occupation, co-residence/Other address | These facts are now collected; implement model/reader/review rather than ask again. Birth country and other spouse gaps remain. |
| C030 | `Possui teste de proficiência em alguma dessas línguas?` | Test indicator is now collected, but designated-agency qualification/details remain unverified. |
| C038 | `País de emissão` inside identity-document block | National-ID country is now collected; add model/reader assignment. Do not confuse with passport issuing country. |
| C064 | `Qual seu nível de formação educacional mais recente (completo ou incompleto)?` | Existing education-level exact-match header is stale; recent education still does not necessarily mean highest post-secondary education. |
| C105–120 | Two parent blocks, including marital status and death details | Latest labels say genitor; archive labels also allowed guardians. Preserve Parent1/Parent2 without inferring father/mother. |
| C122–165 | Five separate eight-field child blocks, four continuation flags | Replaces a single combined child narrative. No need to request these already structured facts again. Names remain combined, and birth country is still absent. |
| C166–167 | Siblings abroad only, including immigration status narrative | Narrower scope than previous all-siblings question; cannot establish all siblings generally. |

The CSV exports verify headers and response values, **not Google Forms branching,
requiredness, option lists or current page layout**. The relationship loop and
required-upload inconsistencies seen in the PDF should be checked in the live
form; their presence in this newer form cannot be established from CSV alone.

## Latest standalone versus archive

The spouse co-residence question moved from archive C019 to latest C008, shifting
residence/marital/spouse columns C009–019. Residence start is now C011, not C010.
Parent labels C105–120 now say genitor and no longer include legal guardians.
The two death-detail labels are no longer identical; the second lacks a parent
number and needs its verified block context. Child blocks 1–4 use simplified
filho labels, while block 5 retains filho(a). C176 now asks why Canada specifically
rather than another country; C186 changes the identity-document upload wording.
These are schema versions, not harmless file-format differences. A fixed-offset
or exact-duplicate-only family parser would mishandle them.

## Duplicate and repeated fields

The fixture preserves exact whitespace and embedded newlines. Normalized
occurrences follow the existing reader's normalization, while exact-header
occurrences are recorded separately. Applicant `E-mail ` has a trailing space;
host `E-mail` does not. They are different exact strings but the reader treats
them as the same label. This distinction matters for both drift detection and
safe role assignment.

| Normalized label/role | Current indexes |
| --- | --- |
| Cidade: applicant, then activities 1–4 | C043, C082, C089, C096, C103 |
| Telefone: applicant, host | C047, C062 |
| E-mail: applicant, host | C046, C063 |
| Activity blocks, six data columns then continuation flag | C077–083, C084–090, C091–097, C098–104 |
| Parent death-details fields (different latest labels; identical in archive) | C111, C119 |
| Child block starts (`Tipo de Filiação`) | C122, C131, C140, C149, C158 |
| Child combined names: four latest `Nome completo do filho` plus older `Nome completo do filho(a).` | C123, C132, C141, C150; C159 |
| Child continuation flags | C130, C139, C148, C157 |

Each child block contains filiação, full name, DOB, marital status, birth city/state,
occupation, address and accompanying indicator. The fifth has no continuation
column; overflow beyond five still needs a reviewed process. Activity history
still has four blocks. Current employment remains separate at C070–075.

## Existing-reader results

The existing CSV reader successfully imports each response independently. The
latest standalone response has 138 nonempty cells and 69 blank cells (the archive
had 123 and 84). Each imports one activity and produces three current validation
warnings. Those warnings concern the intentionally unguessed name
components/sex; the narrow current validator does not detect every coverage gap.
No client values are needed to describe the findings:

- Residence start C011 and education level C064 contain answers, but the intended
  model fields stay empty because the current exact header aliases do not match.
- Host C062/C063 contain answers, but `trip.host_phone` and `trip.host_email` stay
  empty because there are no assignments.
- Applicant city/email/phone are populated on this particular response. The known
  fallback bugs therefore do not trigger on it. Synthetic blank-applicant variants
  using the **actual** header sequence reproduce all three defects.
- New spouse, language-test, national-ID-country, family and child data have no
  domain assignments. All columns are retained in `raw_response`; that is not
  semantic model coverage.

To separate blank/conditional responses from absent mappings, a fully populated
synthetic row with the exact current headers was also imported:

| Category | Column count |
| --- | ---: |
| Assigned to model fields | 77 |
| Of those, susceptible to cross-person/activity fallback when blank | 3 |
| Unmapped existing model fields: C011, C062, C063, C064 | 4 |
| Source data needing domain-model additions | 125 |
| Timestamp metadata without a domain assignment | 1 |
| Total unassigned columns, including timestamp | 130 |

Thus 74 assignments showed no cross-column error in this experiment, but storage
correctness is not proof that a value matches official question semantics. The
matrix retains conditions for funds vs spending, residence vs status dates,
parent/guardian roles, birth city vs country, and scoped immigration questions.
The lower mapped count relative to the old PDF projection (79) is explained by
the two renamed headers, not by loss of duplicate columns.

## Coverage matrix and exact official targets

`canada/coverage_matrix.yaml` now has 207 current `source_fields`, a current
`source`/`reader_audit`, an `archive_csv_baseline`, and a preserved
`pdf_schema_baseline`. Each baseline retains its own column/response evidence. Actual source headers
are verbatim. `occurrence` is normalized, `exact_header_occurrence` is literal,
and `csv_index` is authoritative only for the recorded header fingerprint.

The existing 293 target locators and three template hashes remain unchanged and
are verified by the tests. New spouse, parent and child references reuse exact
packet/hierarchical paths, not bare names. Parent slots retain explicit Parent1/Parent2 correspondence; repeated `Child[0]` paths denote the prototype and do not imply
that five children should be written to one runtime instance. The matrix is
coverage evidence, not a generation implementation.

## Updated required changes

### Google Form

Keep the new spouse details, proficiency-test question, ID issuing country,
parent marital/death details and five structured child blocks. Normalize the
inconsistent labels between child blocks 1–4 and block 5. Do not re-add
those facts under duplicate labels. Still collect applicant separate passport
names, sex and birth country; separate name components/birth countries for family
members; missing spouse/accompanying facts; funds available in CAD; structured
address/phone roles; highest post-secondary education/location; activity countries,
ongoing status and overflow; and the precisely scoped background questions from
the original review. Confirm test agency qualification. Keep the latest explicit parent roles; if
supporting older guardian-inclusive exports, require role clarification. Preserve sibling-abroad scope without assuming it
covers all siblings. Verify live-form routing and requiredness separately.

### CanadaCase

Add the newly confirmed spouse fields, `identity.language_test`, national-ID
issuing country, two role-aware parent records with marital/death details,
and repeatable children with source block provenance. Do not name parent slots
father/mother or split combined names. Preserve raw unknown/N/A/deceased answers
without inventing facts. Add the previously documented residence, travel,
immigration/background, letter, attachment and consent components. Existing
`identity.residence_since`, `education.level`, `trip.host_phone` and
`trip.host_email` need reader fixes, not new duplicate model fields.

### source_readers.py

1. Recognize both verified residence-start and education-level labels, preserving
   compatibility with the historical labels.
2. Bind normalized occurrences to verified applicant/host/activity roles, retaining
   blank values. Do not use first-nonempty duplicate lookup for role-specific data.
3. Bind generic C038 `País de emissão` inside the verified ID block; never make it
   a broad passport-country fragment match.
4. Preserve two parent blocks and five child blocks by stable semantic IDs or
   verified schema layout. Support the two actual header fingerprints separately,
   including the moved spouse-address field and mixed child-label variants. Keep blank blocks and continuation flags as
   provenance; never infer roles or runtime indexes from compacted list positions.
5. Continue preserving all raw fields and detect unknown/reordered layouts. The
   current fingerprint is evidence for this export, not a universal fixed-offset
   parser. Validate dates/enums and distinguish blank/No/N/A/unknown.

### Review UI and representative settings

Add editable, provenance-aware spouse/parent/child sections, including role,
marital/death and accompanying data. Show the four currently unassigned existing
model fields as intake issues and expose contact-role conflicts. Reconcile child
and activity overflow and require explicit missing facts. The separate Canada
representative settings plan is unchanged: none of these host or family fields
supply a representative's identity, authorization, credentials or contact details.
Keep official signatures and signing dates manual.

## Validation and stopping point

Full suite: **46 tests, 40 passes and six expected failures**. Four existing
future-facing failure cases now run against current CSV headers; two new ones
cover the renamed residence/education headers. Historical PDF-schema tests remain
separate. Additional checks cover exact header fingerprint/whitespace, five child
blocks, variant-specific parent death labels, both layout fingerprints, all 207
raw values, current mapping counts and
updated gap claims. All fixtures use generated marker values only.

The Australia smoke test passes. No raw response or archive is committed, and no
runtime parser/model/UI/settings change or Canada generation is implemented.
