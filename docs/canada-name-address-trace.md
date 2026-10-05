# Verified name/address trace — 2026-10-01

The supplied 234-column test CSV matches the existing exact header fingerprint.
Its response values were checked locally; the file was not copied into the
repository or changed. New regression tests construct fictional responses using
the existing header fixture.

## Diagnosis and checkpoints

No applicant-name loss was reproduced in the active pipeline. The old importer
already assigned index 1 to `identity.family_name` and index 2 to
`identity.given_names`. Both survive preparation, review creation, serialization
and all three official draft mappers. A missing-name review was not emitted.
The source's example remains `Costa Almeida` / `Mariana` at every checkpoint.
There is no evidence justifying a name swap or a second model.

The residential address also survived import, preparation and review correctly.
The failure was at the **IMM5257 mapper**: it consumed only the internal
`official_review.residential_street_name`, leaving the street target blank while
`contact.address` contained the complete CSV address. City and postcode were
already mapped. Address-country confirmation was not the cause of the omission.

| Stage | Before | After |
| --- | --- | --- |
| Verified import | Names, complete address, city/state/postcode present | Same exact values |
| Preparation/review | Values preserved | Preserved, with verified source recovery when a stale override/derived value exists |
| Save/reopen | Values preserved | Values preserved; regression verified |
| IMM5257 applicant names | Correct canonical fields | Unchanged |
| IMM5257 residential street | Empty unless staff entered structured street | Complete canonical address fallback or continuation reference |

The canonical address remains the original string including whitespace, line
breaks and accents. The existing IMM5257 export normalization still converts
unsupported Portuguese accents, e.g. `Acácias` to `Acacias`; it does not change
the case or CSV. The continuation preserves accents. The model's existing names
are `contact.postcode` and `identity.residence_country`, not new aliases.

## Implemented behavior

- Verified original name/address cells are recovered during preparation when
  no valid source-bound staff override exists. Valid field-level staff overrides
  retain priority. Repeated city/state labels are resolved by the verified
  positional contract. No CSV interpretation was added to the PDF mapper.
- The complete address supplies the draft street target independently of country
  confirmation. A staff-entered structured street remains authoritative.
- The pinned residential street field permits 100 characters. Longer addresses
  receive a short continuation reference instead of silent truncation. Every
  full-address fallback is also preserved on the supplementary sheet, including
  city, state and postcode. The sheet is created even without activity overflow.
- The report identifies the fallback as needing street/unit/number and visible-fit
  review in Acrobat. This does not claim that an unsplit address is a final
  structured official street name. No guessed address components are introduced.
- Spouse, former spouse and parents already used direct component mappings.
  The five current-schema child name columns now also map directly to given names.
  Shared surname/given-name tokens are not removed. Older saved combined-name
  records retain the previous preparation compatibility behavior.
- IMM5707 has no applicant residential-address node in the pinned template;
  no fictitious field was added. Its applicant name fields and IMM5476 applicant
  name fields continue consuming the canonical name components.

## Changed files and tests

`verified_intake.py`, `preparation.py`, `pdf_drafts.py`, `continuation.py`, and
`coverage_matrix.yaml`; new `test_canada_name_address.py`, plus updated expectations
in `test_canada_pdf_drafts.py` and `test_canada_verified_intake.py`.

Ten new tests cover exact mapping, whitespace preservation, unrelated review and
country confirmation, absence of missing-name issues, save/reopen, actual PDF
dataset values, repeated city/state isolation, family component pairs, valid vs
stale override precedence, and structured-street/long-address fallback.

The full staged suite passes **166 tests**. The supplied test CSV passes all six
field equality checks at import, preparation, review and reload; the generated
IMM5257 contains both names and an address, and its report attributes the address
to `contact.address`. The CSV SHA-256 is unchanged. A synthetic supplementary
sheet was rendered and visually checked. Native XFA field fit still requires
Acrobat review; dataset verification is not a visual approval of all official pages.
