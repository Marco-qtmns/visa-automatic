# Authentication foundation (M10A)

Visa Automatic authenticates employees in FastAPI before any business router is
entered. Network or Tailscale reachability is not treated as identity.

## Bootstrap

After applying migrations through `0012_import_raw_provenance`, create the first administrator
inside the backend container. The password is read interactively and is never a
command-line argument:

```bash
python -m backend.scripts.create_admin \
  --email admin@example.com \
  --display-name "Administrator"
```

The administrator signs in at `/login` and enrolls an authenticator application.
Additional employees can be created with the ADMIN-only `POST /auth/users`
endpoint. A graphical account-management screen is deferred to M10B.

## Security design

- Passwords use Argon2id. Emails are stripped, case-folded, uniquely indexed,
  and constrained to their normalized lowercase form.
- TOTP secrets are encrypted with `MFA_ENCRYPTION_KEY` (Fernet). Enrollment is
  activated only after a valid six-digit code. Verification permits one 30-second
  step of clock skew in either direction.
- Password success creates a five-minute, one-time, server-side MFA challenge,
  not an application session. Five bad codes consume the challenge.
- Application sessions last `AUTH_SESSION_HOURS` (12 by default). The browser
  receives an opaque `HttpOnly`, `Secure`, `SameSite=Strict`, path-wide cookie;
  PostgreSQL stores only its SHA-256 digest. Logout revokes the database row.
- A separate non-HttpOnly CSRF cookie contains no authentication credential. Its
  hash is bound to the server-side session and every unsafe authenticated request
  must echo it in `X-CSRF-Token`.
- Password attempts are tracked in PostgreSQL per normalized identifier and
  client address. Five failures in a 15-minute window cause a 15-minute lockout.
- Security events contain event type, time, user identifier where known, and at
  most a one-way subject digest. Credentials and request payloads are not logged.

The public backend allowlist is `/health`, `/health/live`, `/health/ready`,
`/auth/login`, and `/auth/mfa/verify`. `/auth/me` and `/auth/logout` require a
valid session. All business routers share a fail-closed authentication/CSRF
dependency at the aggregate router boundary.

## Deployment dependency guard

`requirements.deploy.txt` is the production dependency authority. The backend
image runs `python -m backend.scripts.runtime_import_smoke` during its build, and
deployment preflight runs the same check at container startup. Missing Argon2,
Fernet, email validation, or the standard-library TOTP implementation therefore
fails closed with the stable code `auth_runtime_dependency_missing` instead of a
raw import traceback.

## Deferred to M10B / production follow-up

Recovery codes are intentionally not included in M10A rather than shipping a
weak implementation. M10B should add high-entropy one-time recovery codes stored
only as password-grade hashes, plus administrator-driven MFA reset and a complete
account activation/deactivation UI and audit workflow.
