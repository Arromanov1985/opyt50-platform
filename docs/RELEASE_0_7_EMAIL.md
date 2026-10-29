# Release 0.7 — production email

## Scope

Release 0.7 replaces the demo-only email path with optional real SMTP delivery while preserving the local `email_outbox` as a fallback/audit trail.

Covered flows:

- email verification;
- password reset;
- application/invitation workflow notices;
- welcome and account notifications.

## Runtime variables

Required to enable real delivery:

- `OPYT50_PUBLIC_URL` — public HTTPS site URL used in reset/verification links;
- `OPYT50_SMTP_HOST`;
- `OPYT50_SMTP_PORT`;
- `OPYT50_MAIL_FROM`.

Usually also required:

- `OPYT50_SMTP_USER`;
- `OPYT50_SMTP_PASSWORD`.

Transport selection:

- STARTTLS (default): `OPYT50_SMTP_STARTTLS=1`, `OPYT50_SMTP_SSL=0`;
- implicit TLS: `OPYT50_SMTP_SSL=1`, `OPYT50_SMTP_STARTTLS=0`.

No SMTP credentials belong in GitHub.

## Safety properties

- With no SMTP configuration, the application remains in outbox-only mode.
- SMTP failures do not abort registration, applications, invitations or password-reset requests.
- Reset and verification tokens are not returned in API responses.
- The password-request endpoint always returns a generic success response whether the email exists or not.
- Recovery and verification endpoints are rate limited.
- Password reset invalidates all existing sessions for the account.
- Reset/verification tokens are single-use and expire.

## Timeweb rollout

1. Merge only after Python/browser/PostgreSQL CI is green.
2. Add SMTP variables in Timeweb App Platform environment settings; do not put secrets in source control.
3. Set `OPYT50_PUBLIC_URL` to the production HTTPS origin.
4. Redeploy.
5. Verify `/api/health`.
6. Test with a controlled mailbox:
   - request email verification;
   - confirm through the received link;
   - request password reset;
   - change password through the received link;
   - confirm the old password no longer works;
   - confirm previously issued sessions are invalidated.
7. Verify no reset token or SMTP password appears in application logs.
8. If delivery fails, remove/disable the SMTP host variable to fall back to outbox-only mode without changing database state.

## Production dependency still needed

A real sending mailbox/provider must exist before SMTP can be enabled. The code does not assume a specific provider.
