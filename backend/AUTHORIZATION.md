# Authorization and audit

Authentication remains the M10A session, MFA, cookie, and CSRF boundary. M10B adds a
static `Permission` enum and `UserRole` to permission mapping in
`backend/app/authorization.py`. Every effective FastAPI operation is declared as
`PUBLIC`, `AUTHENTICATED`, `PERMISSION_REQUIRED`, or `ADMIN_ONLY`; the route-graph
regression test fails closed when a new endpoint has no declaration.

`CASE_WORKER` has the operational permissions, including preparation and transitions
through `PREPARE -> REVIEW`. `REVIEWER` adds final review, submission, and case-audit
access. `ADMIN` has every permission, including user and security administration.
The workflow target policy applies the final-review gate before the existing
`WorkflowService` validates its state-machine invariants.

Administrative session revocation intentionally allows self-revocation: the current
request finishes transactionally, while the stored session is invalid on the next
request. Deactivation and MFA reset revoke active sessions and consume outstanding MFA
challenges in the same database transaction. MFA reset also clears enrollment and the
encrypted secret, so the next password login starts enrollment again.

M10A `auth_security_events` remains the authentication-event ledger. M10B adds
append-only `application_audit_events` for administration and business activity. Case
timelines are newest-first. Audit metadata is deliberately minimized and recursively
rejects secret-bearing keys; payloads, document content, credentials, and tokens are
never copied into audit rows.

Business-route audit intents are queued before endpoint execution and materialized by
the SQLAlchemy `before_commit` hook. The audit insert therefore participates in the
same transaction as the service mutation; an audit write failure rolls back that
mutation. Case creation, workflow, preparation, and authentication-administration
lifecycle events are inserted directly at their owning service commit boundary.

Authorization keys use endpoint function names. This remains safe only while those
names are globally unique: the effective-route-graph regression test compares every
method/path identity and fails if a name collision is introduced.
