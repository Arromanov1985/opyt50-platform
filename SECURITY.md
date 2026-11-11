# СТАЖНО — security baseline

This file describes the application's security baseline. It is a target and an
operational checklist, not a claim of bank certification.

## Application controls already enforced

- Opaque random server-side sessions; only a SHA-256 digest of a session token is stored.
- Production sessions use HttpOnly, Secure, SameSite=Strict and the __Host- cookie prefix.
- New and reset passwords require at least 15 characters.
- Passwords are stored with Argon2id. Legacy PBKDF2 hashes are upgraded after a successful login.
- Login performs a dummy password verification for unknown email addresses to reduce account-enumeration timing differences.
- Password reset revokes every session for the account.
- New-device login alerts use a random HttpOnly device cookie; only an account-scoped hash is stored. Raw IP addresses are not persisted for device recognition.
- Disabling an account revokes its sessions.
- Reset/verification tokens are single-use, stored only as hashes, and are not persisted in email_outbox bodies.
- State-changing API calls require a same-origin custom request header; CORS is not enabled.
- Role and ownership checks are enforced server-side.
- Public candidate matching does not expose name, phone or email before consent/opening.
- CSP, HSTS, clickjacking protection, Permissions-Policy, COOP/CORP and no-sniff headers are emitted.
- Production OpenAPI/Swagger endpoints are disabled by default.
- API responses containing account data are no-store.
- API requests have a basic body-size guard.
- pip-audit, Bandit, CodeQL and the repository secret scanner run in CI; Dependabot monitors Python, GitHub Actions and Docker dependencies.
- CodeQL scans Python and JavaScript.
- The container runs as an unprivileged Linux user and hides the Uvicorn Server header.

## Mandatory production environment

Set and verify these in Timeweb, not in GitHub.

Current working public origin for this stage: https://arromanov1985-opyt50-platform-fdd8.twc1.net
When the project moves to stazhno.ru, change the environment value; do not hard-code the domain in application logic.

Required values:

- OPYT50_ENV=production
- OPYT50_PUBLIC_URL=https://arromanov1985-opyt50-platform-fdd8.twc1.net
- OPYT50_COOKIE_SECURE=1
- OPYT50_ENABLE_DOCS=0
- OPYT50_DB_SSLMODE=verify-full when the provider CA/hostname configuration supports it; otherwise require is the temporary minimum
- OPYT50_ALLOWED_HOSTS=arromanov1985-opyt50-platform-fdd8.twc1.net plus only legitimate Timeweb health/platform hostnames that actually reach the app
- OPYT50_PREVIEW_SEED_DEMO=0
- OPYT50_ADMIN_MFA_MODE=hybrid after at least one administrator passkey is enrolled; keep `totp` during initial enrollment
- OPYT50_ADMIN_TOTP_SECRET=<random Base32 secret stored only in Timeweb secret/environment UI; retained as hybrid fallback>
- strong, unique PostgreSQL and SMTP credentials

Never run demo seeding against production.

## Required infrastructure before calling the service "bank-grade"

Application code alone cannot provide a bank security perimeter. The production
environment still needs:

1. Extend phishing-resistant WebAuthn/passkeys beyond the administrator account to privileged employer/support roles. Administrator passkeys are implemented with TOTP fallback; production must enroll and test at least two independent authenticators before switching to hybrid mode.
2. Managed WAF, DDoS protection and distributed rate limiting in front of App Platform.
3. Centralized immutable security logs/SIEM with alerting for admin actions, auth abuse and anomalous access.
4. Encrypted PostgreSQL backups, tested point-in-time restore and documented RPO/RTO.
5. Database TLS identity verification (verify-full), least-privilege DB accounts and credential rotation.
6. Central secrets manager/KMS; no long-lived secrets in repository, images or logs.
7. Regular external penetration testing and authenticated DAST against a staging copy.
8. Incident-response runbook, credential/session revocation procedure and on-call ownership.
9. Data-retention/deletion policy and field-level protection for high-value personal data.
10. GitHub branch protection/rulesets: required CI, required review, no force-push to main.

## Security review cadence

- Every push: tests, dependency audit, CodeQL/JS syntax as configured.
- Weekly: dependency updates and review of security alerts.
- Monthly: access review for admin/hosting/GitHub/DB/SMTP accounts.
- Quarterly: restore drill, secrets review and threat-model update.
- Before major releases: staging DAST and manual authorization/privacy regression.
- At least annually, and after major architecture changes: independent penetration test.

Reference baseline: OWASP ASVS 5.0 plus current OWASP cheat sheets and NIST SP 800-63B authentication guidance.


## Reporting a vulnerability

Do not publish exploitable details, credentials or personal data in a public
issue. Use GitHub's private **Report a vulnerability / Security Advisory** flow
when available. If private reporting is not enabled, contact the repository
owner through the established private business channel.

Include the affected component, impact, prerequisites and minimal reproduction
steps. Use fictional/test accounts. Do not perform denial-of-service, credential
stuffing, social engineering, destructive database actions or access unrelated
user data.

Passing automated checks is not a certification and does not replace an
independent penetration test.


## Public origin during domain cutover

Until the custom domain is attached to the same production deployment, keep:

`OPYT50_PUBLIC_URL=https://arromanov1985-opyt50-platform-fdd8.twc1.net`

Do not switch `OPYT50_PUBLIC_URL` to `https://stazhno.ru` early. This value is used in
password-reset/verification links and as the WebAuthn RP/origin binding. Register new
administrator passkeys only after the final custom domain is live, otherwise those
credentials will be tied to the temporary Timeweb hostname.
