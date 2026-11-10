"""Tests for the non-secret production security preflight."""
from scripts.security_preflight import assess


def configure_safe(monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_PREVIEW_SEED_DEMO", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "totp")
    monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", "A" * 32)
    monkeypatch.setenv("OPYT50_ALLOWED_HOSTS", "stazhno.ru,www.stazhno.ru")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example.invalid/app")
    monkeypatch.setenv("OPYT50_DB_SSLMODE", "verify-full")
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("OPYT50_SMTP_STARTTLS", "1")
    monkeypatch.setenv("OPYT50_SMTP_PASSWORD", "smtp-secret-value")


def test_security_preflight_passes_strict_configuration(monkeypatch):
    configure_safe(monkeypatch)
    result = assess()
    assert result["ok"] is True
    assert result["errors"] == []
    assert result["checks"]["admin_mfa"] == "totp"
    assert result["checks"]["host_allowlist_configured"] is True
    assert result["checks"]["database_tls_enforced"] is True


def test_security_preflight_detects_unsafe_configuration(monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "http://example.invalid")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "0")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "1")
    monkeypatch.setenv("OPYT50_PREVIEW_SEED_DEMO", "1")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@db.example.invalid/app")
    monkeypatch.setenv("OPYT50_DB_SSLMODE", "disable")
    result = assess()
    assert result["ok"] is False
    joined = " | ".join(result["errors"])
    assert "runtime mode is not production" in joined
    assert "public origin is not HTTPS" in joined
    assert "administrator MFA is disabled" in joined
    assert "PostgreSQL TLS is not enforced" in joined


def test_security_preflight_never_returns_secret_values(monkeypatch):
    configure_safe(monkeypatch)
    result = assess()
    serialized = repr(result)
    assert "smtp-secret-value" not in serialized
    assert "postgresql://user:secret" not in serialized
    assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in serialized
    assert "stazhno.ru" not in serialized
