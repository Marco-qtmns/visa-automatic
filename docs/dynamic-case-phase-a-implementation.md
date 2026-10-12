# Dynamic Case Management — Phase A stabilization

Status: implemented on `codex/dynamic-case-phase-0` after the Phase 0
architecture review.

## Delivered

- Section confirmation is a single backend transaction. Valid populated fields
  are confirmed together; conflicts, ambiguous values, rejected proposals,
  missing values, and validation failures remain unresolved and are returned as
  explicit skipped results.
- Confirmation of an already applied value can recover its canonical entity
  from the audited mapping and application aggregate when an older import row
  has a missing or stale target ID.
- Regression coverage fixes the reported values exactly: applicant city
  `Campinas`, passport `BRTESTP000001`, identity number
  `RG-TESTE-123456789`, and travel purpose `Turismo`.
- A rejected import proposal no longer appears as a confirmed canonical field.
  Rejection reviews the proposal, not an absent canonical value.
- Migration `0016_import_review_state` persists section and field review state,
  so confirmation survives reloads independently of candidate application.
- Sponsor and host decisions are available in the normal case screen as
  explicit unknown/yes/no choices with required person selection for “yes”.
  Saving replaces primary funding/host assignments and synchronizes operational
  roles and confirmed facts.
- The desktop workspace cap increased from 1240px to 1520px while retaining the
  existing responsive mobile width.
- Employee import responses retain their compatibility shape but no longer
  expose raw warnings or failure details. Raw run diagnostics and the mapping
  specification require the admin-only `LEGACY_DIAGNOSTICS_READ` permission.

## API additions

- `POST /canada-imports/{import_id}/confirm-section`
- `GET /canada-imports/{import_id}/diagnostics` (admin-only permission)

Existing single-field confirmation and import endpoints remain available.

## Verification gate

- Full backend suite: 462 tests passed.
- Frontend suite: 64 tests passed.
- Next.js production build and TypeScript validation passed.

## Deferred by design

Phase A does not add the Phase B lifecycle, canonical decision service,
revision counters, readiness dimensions, or unified issue model. No competing
Canada review aggregate was introduced.
