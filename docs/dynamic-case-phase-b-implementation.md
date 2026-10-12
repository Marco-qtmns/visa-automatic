# Dynamic Case Management — Phase B foundation

Status: implemented on `codex/dynamic-case-phase-0` after the Phase A
stabilization.

## Delivered

- Empty, manual, CSV, and Commercial-message entry paths remain independent.
  No conversation or import record is required before a Case can be edited.
- A provider-neutral canonical decision service writes the existing typed
  Canada aggregate and an immutable per-field revision ledger. Revisions retain
  original and normalized values, source metadata, review state, reviewer, and
  timestamps. Manual saves submit expected field revisions and reject stale
  browser updates instead of overwriting newer confirmed information.
- The normal Case workspace provides one manual canonical intake form for
  applicant identity, contact details, visa and destination, travel purpose,
  sponsor and host decisions and identities, payer, Commercial instructions,
  special circumstances, and notes.
- Unknown sponsor and host values remain unresolved. Confirmed changes rerun
  the existing Requirement Engine; sponsor identity is reflected in the
  funding source and requirement owner.
- Accepted or corrected Commercial-message candidates write the same canonical
  revision ledger. Candidates remain evidence until an employee decision and
  visibly distinguish explicitly stated values from inferred information.
- The target lifecycle `NEW → ACTIVE → FINAL_REVIEW → READY → SUBMITTED` is a
  compatibility projection over the existing workflow enum. Existing history,
  APIs, permissions, and stored states remain intact.
- Ordinary ACTIVE work no longer requires complete facts or documents.
  Canonical and documentary prerequisites are enforced when entering final
  review; final approval gates remain in place.
- One backend-derived Open Issues projection combines readiness blockers,
  unresolved source candidates, sponsor/host decisions, missing party identity,
  and open tasks. React displays this projection instead of recreating those
  rules.
- Separate intake, canonical, document, and issue readiness dimensions are
  exposed and displayed in the Case workspace.

## Schema and API

Migration `0017_dynamic_case_foundation` adds:

- `canonical_value_revisions`, an immutable provider-neutral value history;
- `fact_extraction_candidates.assertion_type`, with `explicit` as the safe
  compatibility default.

New endpoints:

- `GET /cases/{case_id}/dynamic-status`
- `POST /cases/{case_id}/canonical-decisions`
- `GET /cases/{case_id}/canonical-revisions`

Existing workflow, import, conversation, requirement, preparation, and Canada
application endpoints remain compatible.

## Verification gate

- Repository-wide Python suite: 467 tests passed.
- Frontend suite: 64 tests passed.
- Next.js production build and TypeScript validation passed.

## Boundaries

- Phase B does not implement the Phase C document-processing pipeline or the
  Phase D final generation sequence.
- Commercial extraction remains behind the replaceable provider interface. The
  bundled local rules cover only supported payer/sponsor/host phrases and never
  confirm their output automatically.
- Safe cross-Case identity matching and live provider integrations remain part
  of the later integration boundary; employees associate new evidence with a
  selected Case today.
