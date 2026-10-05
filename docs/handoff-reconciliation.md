# Visa Automatic handoff reconciliation

Inspected 2026-09-28 at baseline `aae5181` on `main`, clean and 14 commits ahead of `origin/main`.
The actual repository directory is `9656A Generator Australia`; the supplied workspace path
`96556A Generator Australia` does not exist.

## Verified implementation

| Handoff item | Repository evidence and status |
| --- | --- |
| Australia packages, compatibility shims, template paths | Present; regression and smoke tests pass. |
| Workflow registry and CLI adapter | Present; CLI still intentionally selects Australia only. |
| Australia CEP/UF fallback | Committed in `22e7274`; explicit fields win and city is not inferred. |
| Australia address deduplication | Present in `build_field_values`; regression test passes. |
| Australia intake validation and GUI warning | Committed in `61cedc1`; formatted CEP-only gap fixed in this continuation. |
| Canada aggregate model and duplicate-preserving CSV reader | Present; synthetic importer tests pass. |
| Canada GUI review and multirow selection | Present at baseline despite no standalone review commit; routing covered by new tests. |
| Canada generation guard | Present in GUI and workflow; no Canada documents generated. |
| Country-specific GUI controls | Baseline showed Australia controls for Canada; now hides the Australia panel and offers Canada review. |
| Canada templates and inventory | Committed in `aae5181`; rerunning the inspector exactly reproduces the tracked inventory. |
| Verified Canada coverage matrix | Not present; requires the actual current CSV headers. |

## Canada PDF findings

These describe the bundled files, not verification that they are the latest IRCC releases.

| File | Pages visible to PyMuPDF | AcroForm widgets | XFA |
| --- | ---: | ---: | --- |
| IMM5257.pdf | 1 | 1 (signature) | Present |
| IMM5707.pdf | 1 | 0 | Present |
| IMM5476.pdf | 4 | 76 | Present |

IMM5476 is a hybrid with both widgets and XFA, rather than an AcroForm-only file.
A future generator must check that saved values and XFA/Adobe behavior agree.
The existing inventory lists bare XFA names, including duplicates and auxiliary packets;
it is a preliminary inventory, not an unambiguous mapping specification. Before mapping,
record packet identity, full hierarchical paths, repeat indexes and template hashes.
No template was modified and no signatures were filled.

## Remaining work and required evidence

No actual Canada CSV was found in this repository or the adjacent `Canadian Visa Process`
folder. The latter contains official PDF copies and an older intake DOCX, which cannot
establish current Google Sheets headers. The current phase therefore remains incomplete.

1. Obtain the real Canada CSV (a header-only copy suffices for schema work); verify
   duplicate labels, applicant/host phone and email positions, and activity block ordering.
2. Build the coverage matrix from those headers and the exact PDF paths. Do not equate
   parser string literals or synthetic fixtures with verified intake headers.
3. Then extend the domain model and manual correction UI from verified requirements.
   The current Canada review is read-only. Name components and sex remain unguessed.
4. Implement and validate IMM5476 first, followed by an XFA-aware strategy for the other
   forms. Keep generation blocked until mappings and required data are verified.
5. Bundle Canada templates when generators make them runtime dependencies; the current
   Windows packaging still covers Australia. Canada CLI selection is future work.

## Validation

Baseline: all 15 unit tests and the Australia smoke test passed.
Continuation: all 21 unit tests and the Australia smoke test passed in the staged copy.
New tests cover formatted CEP-only addresses, country switching, selected Canada records,
reopening review and the Canada generation guard. GUI routing tests use mocks; an actual
interactive Tk/Windows packaging check has not been performed. Smoke PDFs remain ignored.
