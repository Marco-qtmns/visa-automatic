# Verified September 29 Canada intake

Sources: `CANADÁ - TURISMO 2Marco.csv` (234 columns, one response) and
`Google Form questions.pdf` (42 screenshot pages, no text layer). All supplied
pages were visually reviewed. Repeated pages omitted by the user were not
invented: the CSV supplies all repeated headers and their order. Input files were
read only. No actual answers, account identifiers, attachment URLs or screenshots
are committed. Source hashes and header-only evidence are in the schema fixture
and coverage matrix.

## Import result

Before this change the supplied response failed on the two occurrences of
`País de nascimento do genitor 1`. The new dedicated profile imports it and stores
all 233 domain columns separately. The submission timestamp remains in
`raw_response`. This includes 21 document-reference fields and the declaration
answer: storing those is not document processing or official consent/signature
generation. No referenced attachment is downloaded.

The exact ordered header SHA-256 is
`81820c7095e89bb2809f1c674838a95a088524b15efa4e70827a7b535ac0117b`.
Only that complete schema may use the index mapping in `verified_intake.py`.
Altered schemas cannot reuse its offsets. Earlier two 207-column profiles remain
tested; their evidence is retained under `pre_20260929_baseline` in the matrix.

## Actual findings and handling

| Evidence | Handling |
|---|---|
| Applicant surname C001 and name C002; screenshot 42 | Import separate components. There is no separate full-name control answer. Use a display-only combined label in client selection; do not manufacture a source full name. |
| No applicant sex or birth-country column | Leave blank for explicit staff confirmation. Nationality and birth state are not substitutes. |
| Spouse surname/name C016/C017, birth country C019, co-residence C021, accompanying C022 | Import independently. Co-residence uses Sim/Other-address in one answer; preserve it without copying applicant address or inventing a separate yes/no. |
| Former spouse surname/name C024/C025 and birth country C027 | Import. The current export has no former-spouse co-residence/accompanying questions; those remain unset. |
| Parent country C117 and C127 both say genitor 1; screenshots 15/16 locate the latter in block 2 | Map C127 to parent block 2 only under the full verified fingerprint. Empty block 1 never falls back to block 2. A later label correction requires a new verified fingerprint. |
| Parent 1/2, not explicit mother/father; surname plus Nome completo | Preserve surnames, combined names and birth countries. Confirm mother/father and given names internally. Do not infer roles from order or split combined names. |
| Five child blocks, last block retains older date/marital/accompanying labels | All five mapped independently, including new CEP columns. Blank middle blocks retain their positions and continuation answers. Given names require confirmation because the field still says Nome completo. |
| Residential city/state and four repeated activity city/state pairs | Map exact roles; blank residential values do not fall back to activity values. |
| Applicant and host Telefone/E-mail duplicated across sections | Keep separate. Empty applicant contact never becomes host contact. |
| Current employment C075–C080 plus four additional activity blocks C082–C112 | Preserve five available periods across employment/history, not five extra history records. Staff can add further periods. |
| Activity screenshots instruct today's date for ongoing activities | Keep the entered date; ongoing status stays unknown until staff confirms it. |
| C057 / screenshot 36 asks approximate spending and provides no currency | Preserve `trip.estimated_spend`; do not relabel as `available_funds_cad`. Staff can confirm CAD funds without adding a customer question. |
| Education screenshot 13 | Existing level, course, institution, dates and country retained. Institution city/state and post-secondary context remain internal clarification if needed. |
| Travel, prior residence, siblings abroad and intention-letter narratives | Preserve text, without generating travel records, name splits or immigration answers from it. |
| Applicant uploads C212–C225; sponsor uploads C226–C232 | Keep references under distinct source roles. No download. |

The surname/name-control distinction is deliberate: the user requested no guesses
from combined names. Client-form clarification could rename the ambiguous name
labels later, but staff review works with the present export without requiring
more client inputs.

## Verification

The schema fixture contains exact headers only. Its paired CSV contains only
`SYNTHETIC_R000`–`SYNTHETIC_R233` markers. Tests cover every mapped source column,
duplicate parent countries, blank applicant contacts, blank child blocks, all five
child formats/CEPs, source-role separation for uploads, date/fund uncertainty,
wrong-fingerprint rejection, extra CSV cells, and save/reopen behavior. The real
response is also checked in memory against each mapped source cell; only aggregate
results are reported. Original file hashes are checked before and after work.

Validation result: all 103 automated tests and the Australia PDF smoke test pass.
The real response matches all 233 mapped source cells in memory. Both supplied
file hashes are unchanged. The updated agent YAML parses successfully. GUI
commands are covered by mocked tests; desktop appearance was not manually tested.

Canada official PDF generation remains disabled. Verified schema mapping does
not imply all required facts or the customer's answers have been substantively
validated. The remaining manual checks appear in the review UI and matrix.
