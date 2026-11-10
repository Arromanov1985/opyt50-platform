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
- Disabling an account revokes its sessions.
- Reset/verification tokens are single-use, stored only as hashes, and are not persisted in email_outbox bodies.
- State-changing API calls require a same-origin custom request header; CORS is not enabled.
- Role and ownership checks are enforced server-side.
- Public candidate matching does not expose name, phone or email before consent/opening.
- CSP, HSTS, clickjacking protection, Permissions-Policy, COOP/CORP and no-sniff headers are emitted.
- Production OpenAPI/Swagger endpoints are disabled by default.
- API responses containing account data are no-store.
- API requests have a basic body-size guard.
- pip-audit runs in CI and Dependabot monitors Python and GitHub Actions dependencies.
- CodeQL scans Python and JavaScript.
- The container runs as an unprivileged Linux user and hides the Uvicorn Server header.

## Mandatory production environment

Set and verify these in Timeweb, not in GitHub:

- OPYT50_ENV=production
- OPYT50_PUBLIC_URL=https://stazhno.ru
- OPYT50_COOKIE_SECURE=1
- OPYT50_ENABLE_DOCS=0
- OPYT50_DB_SSLMODE=require (prefer verify-full after configuring the DB provider CA)
- OPYT50_ALLOWED_HOSTS only after listing stazhno.ru plus all legitimate platform health-check hosts
- OPYT50_PREVIEW_SEED_DEMO=0
- strong, unique PostgreSQL and SMTP credentials

Never run demo seeding against production.

## Required infrastructure before calling the service "bank-grade"

Application code alone cannot provide a bank security perimeter. The production
environment still needs:

1. Phishing-resistant MFA/passkeys for administrators and preferably employers.
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
