"""Production security preflight for СТАЖНО.

Prints only control status. Never prints passwords, DSNs, SMTP credentials,
TOTP secrets, tokens, email addresses, or full URLs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import admin_mfa_mode, secure_cookie_enabled  # noqa: E402


def assess() -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    env = os.getenv("OPYT50_ENV", "").strip().casefold()
    public_url = os.getenv("OPYT50_PUBLIC_URL", "").strip()
    docs_enabled = os.getenv("OPYT50_ENABLE_DOCS", "0") == "1"
    demo_seed = os.getenv("OPYT50_PREVIEW_SEED_DEMO", "0") == "1"
    hosts = {
        item.strip().casefold()
        for item in os.getenv("OPYT50_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    db_configured = bool(os.getenv("DATABASE_URL", "").strip())
    db_sslmode = os.getenv("OPYT50_DB_SSLMODE", "").strip().casefold()
    smtp_configured = bool(os.getenv("OPYT50_SMTP_HOST", "").strip())
    smtp_tls = (
        os.getenv("OPYT50_SMTP_SSL", "0") == "1"
        or os.getenv("OPYT50_SMTP_STARTTLS", "1") == "1"
    )
    mfa = admin_mfa_mode()

    if env not in {"prod", "production"}:
        errors.append("runtime mode is not production")
    if not public_url.startswith("https://"):
        errors.append("public origin is not HTTPS")
    if not secure_cookie_enabled():
        errors.append("secure session cookie is disabled")
    if docs_enabled:
        errors.append("API documentation is enabled")
    if demo_seed:
        errors.append("demo seeding is enabled")
    if mfa == "off":
        errors.append("administrator MFA is disabled")
    elif mfa == "email":
        warnings.append("administrator MFA uses email OTP; TOTP/passkey is stronger")
    elif mfa == "totp":
        secret = os.getenv("OPYT50_ADMIN_TOTP_SECRET", "").strip()
        if len(secret) < 32:
            errors.append("administrator TOTP secret is missing or too short")

    public_host = ""
    if public_url.startswith("https://"):
        try:
            public_host = (urlsplit(public_url).hostname or "").casefold()
        except ValueError:
            errors.append("public origin is malformed")
    if not hosts:
        warnings.append("Host allowlist is not configured")
    elif public_host and public_host not in hosts:
        warnings.append("public hostname is not present in Host allowlist")

    if db_configured:
        if db_sslmode not in {"require", "verify-ca", "verify-full"}:
            errors.append("PostgreSQL TLS is not enforced")
        elif db_sslmode != "verify-full":
            warnings.append("PostgreSQL TLS does not verify the server hostname")
    else:
        warnings.append("DATABASE_URL is not configured")

    if smtp_configured and not smtp_tls:
        errors.append("SMTP TLS is disabled")

    checks = {
        "production_mode": env in {"prod", "production"},
        "https_origin": public_url.startswith("https://"),
        "secure_cookie": secure_cookie_enabled(),
        "docs_disabled": not docs_enabled,
        "demo_seed_disabled": not demo_seed,
        "admin_mfa": mfa,
        "host_allowlist_configured": bool(hosts),
        "database_configured": db_configured,
        "database_tls_enforced": (not db_configured) or db_sslmode in {"require", "verify-ca", "verify-full"},
        "smtp_tls_enforced": (not smtp_configured) or smtp_tls,
    }
    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    result = assess()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
