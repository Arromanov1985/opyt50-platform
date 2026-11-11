"""Security regression tests for the production hardening baseline."""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
import pyotp

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.security import (
    LEGACY_PASSWORD_ROUNDS,
    make_password_hash,
    password_needs_rehash,
    verify_password,
)

XHR = {"X-Requested-With": "OPYT50"}


def legacy_pbkdf2(password: str) -> str:
    salt = bytes.fromhex("00112233445566778899aabbccddeeff")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, LEGACY_PASSWORD_ROUNDS
    )
    return "pbkdf2_sha256$" + str(LEGACY_PASSWORD_ROUNDS) + "$" + salt.hex() + "$" + digest.hex()


def test_argon2id_is_default_and_legacy_pbkdf2_remains_verifiable():
    password = "A very long secure passphrase 2026"
    current = make_password_hash(password)
    assert current.startswith("$argon2id$")
    assert verify_password(password, current)
    assert not verify_password(password + "x", current)
    assert not password_needs_rehash(current)

    legacy = legacy_pbkdf2(password)
    assert verify_password(password, legacy)
    assert password_needs_rehash(legacy)


def test_successful_login_transparently_upgrades_legacy_password(tmp_path):
    app = create_app(str(tmp_path / "security.db"))
    password = "Legacy password long enough 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            cursor = db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("candidate", "legacy@example.test", "Legacy User", legacy_pbkdf2(password)),
            )
            db.execute(
                "INSERT INTO candidate_profiles(user_id) VALUES(?)",
                (cursor.lastrowid,),
            )

        response = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "legacy@example.test", "password": password},
        )
        assert response.status_code == 200, response.text

        with database(app.state.db_path) as db:
            upgraded = db.execute(
                "SELECT password_hash FROM users WHERE email=?",
                ("legacy@example.test",),
            ).fetchone()["password_hash"]
        assert upgraded.startswith("$argon2id$")
        assert verify_password(password, upgraded)


def test_new_single_factor_passwords_require_15_characters(tmp_path):
    app = create_app(str(tmp_path / "password-policy.db"))
    with TestClient(app) as client:
        response = client.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Кандидат",
                "email": "short@example.test",
                "password": "12345678901234",
            },
        )
        assert response.status_code == 422


def test_security_headers_and_oversized_api_requests(tmp_path):
    app = create_app(str(tmp_path / "headers.db"))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-frame-options"] == "DENY"
        assert page.headers["referrer-policy"] == "no-referrer"
        assert page.headers["x-xss-protection"] == "0"
        assert page.headers["cross-origin-opener-policy"] == "same-origin"
        assert page.headers["cross-origin-resource-policy"] == "same-origin"
        assert page.headers["strict-transport-security"] == "max-age=31536000"
        assert "geolocation=()" in page.headers["permissions-policy"]
        assert "form-action 'self'" in page.headers["content-security-policy"]

        huge = client.post(
            "/api/login",
            headers={**XHR, "Content-Type": "application/json"},
            content=b"x" * 262_145,
        )
        assert huge.status_code == 413


def test_production_hides_docs_and_sets_strict_secure_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.delenv("OPYT50_ENABLE_DOCS", raising=False)
    monkeypatch.delenv("OPYT50_COOKIE_SECURE", raising=False)
    app = create_app(str(tmp_path / "production.db"))

    with TestClient(app, base_url="https://stazhno.ru") as client:
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/redoc").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404

        response = client.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Безопасный пользователь",
                "email": "secure@example.test",
                "password": "long secure password 2026",
            },
        )
        assert response.status_code == 201, response.text
        cookies = "\n".join(response.headers.get_list("set-cookie")).lower()
        assert "__host-stazhno_session=" in cookies
        assert "secure" in cookies
        assert "httponly" in cookies
        assert "samesite=strict" in cookies



def test_trusted_host_allowlist_rejects_forged_host(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ALLOWED_HOSTS", "stazhno.ru,www.stazhno.ru")
    app = create_app(str(tmp_path / "trusted-host.db"))

    with TestClient(app, base_url="https://stazhno.ru") as client:
        assert client.get("/api/health").status_code == 200
    with TestClient(app, base_url="https://evil.example") as attacker:
        assert attacker.get("/api/health").status_code == 400



def test_cross_site_mutations_are_rejected_by_origin_and_fetch_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    app = create_app(str(tmp_path / "origin.db"))
    body = {
        "role": "candidate",
        "name": "Пользователь",
        "email": "origin@example.test",
        "password": "long secure password 2026",
    }
    with TestClient(app, base_url="https://stazhno.ru") as client:
        wrong_origin = client.post(
            "/api/register",
            headers={**XHR, "Origin": "https://evil.example"},
            json=body,
        )
        assert wrong_origin.status_code == 403

        cross_site = client.post(
            "/api/register",
            headers={**XHR, "Sec-Fetch-Site": "cross-site"},
            json=body,
        )
        assert cross_site.status_code == 403

        same_origin = client.post(
            "/api/register",
            headers={**XHR, "Origin": "https://stazhno.ru", "Sec-Fetch-Site": "same-origin"},
            json=body,
        )
        assert same_origin.status_code == 201, same_origin.text



def test_admin_login_revokes_previous_session_and_uses_short_lifetime(tmp_path):
    app = create_app(str(tmp_path / "admin-session.db"))
    password = "Administrator secure password 2026"
    with TestClient(app) as first:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "admin-security@example.test", "Администратор", make_password_hash(password)),
            )

        login1 = first.post(
            "/api/login",
            headers=XHR,
            json={"email": "admin-security@example.test", "password": password},
        )
        assert login1.status_code == 200, login1.text
        assert "max-age=1800" in "\n".join(login1.headers.get_list("set-cookie")).lower()
        assert first.get("/api/me").status_code == 200

        with TestClient(app) as second:
            login2 = second.post(
                "/api/login",
                headers=XHR,
                json={"email": "admin-security@example.test", "password": password},
            )
            assert login2.status_code == 200, login2.text
            assert second.get("/api/me").status_code == 200
            assert first.get("/api/me").status_code == 401

            with database(app.state.db_path) as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)",
                    ("admin-security@example.test",),
                ).fetchone()[0]
                assert count == 1



def test_admin_email_mfa_requires_second_factor_before_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-mfa.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "mfa-admin@example.test", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "mfa-admin@example.test", "password": password},
        )
        assert login.status_code == 200, login.text
        payload = login.json()
        assert payload["mfa_required"] is True
        assert payload["challenge_id"]
        assert payload["debug_code"].isdigit() and len(payload["debug_code"]) == 8
        assert "set-cookie" not in login.headers
        assert client.get("/api/me").status_code == 401

        wrong = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": "00000000"},
        )
        assert wrong.status_code == 401
        assert client.get("/api/me").status_code == 401

        verified = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["user"]["role"] == "admin"
        assert client.get("/api/me").status_code == 200

        reused = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
        )
        assert reused.status_code == 400

        with database(app.state.db_path) as db:
            events = db.execute(
                "SELECT event_type,detail FROM security_events ORDER BY created_at"
            ).fetchall()
            event_types = [row["event_type"] for row in events]
            assert "admin_mfa_challenge_issued" in event_types
            assert "login_password_verified_mfa_required" in event_types
            assert "admin_mfa_failed" in event_types
            assert "admin_mfa_success" in event_types
            serialized = "\n".join(str(dict(row)) for row in events)
            assert payload["debug_code"] not in serialized


def test_admin_mfa_challenge_locks_after_five_wrong_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-mfa-lock.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "mfa-lock@example.test", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "mfa-lock@example.test", "password": password},
        ).json()
        challenge = login["challenge_id"]
        correct = login["debug_code"]
        wrong = "00000000" if correct != "00000000" else "11111111"

        for attempt in range(1, 6):
            response = client.post(
                "/api/admin/mfa/verify",
                headers=XHR,
                json={"challenge_id": challenge, "code": wrong},
            )
            assert response.status_code == (429 if attempt == 5 else 401)

        blocked_correct = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": challenge, "code": correct},
        )
        assert blocked_correct.status_code in {400, 429}
        assert client.get("/api/me").status_code == 401


def test_admin_security_events_endpoint_is_admin_only(tmp_path):
    app = create_app(str(tmp_path / "security-events.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as admin, TestClient(app) as candidate:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "events-admin@example.test", "Администратор", make_password_hash(password)),
            )

        admin_login = admin.post(
            "/api/login",
            headers=XHR,
            json={"email": "events-admin@example.test", "password": password},
        )
        assert admin_login.status_code == 200

        candidate_registration = candidate.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Кандидат",
                "email": "events-candidate@example.test",
                "password": "candidate secure password 2026",
            },
        )
        assert candidate_registration.status_code == 201

        allowed = admin.get("/api/admin/security-events")
        assert allowed.status_code == 200
        assert isinstance(allowed.json()["events"], list)
        assert candidate.get("/api/admin/security-events").status_code == 403



def test_login_throttle_limits_repeated_failures_for_same_identity_and_source(tmp_path):
    app = create_app(str(tmp_path / "login-throttle.db"))
    password = "Candidate secure password 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            cursor = db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("candidate", "throttle@example.test", "Кандидат", make_password_hash(password)),
            )
            db.execute("INSERT INTO candidate_profiles(user_id) VALUES(?)", (cursor.lastrowid,))

        for _ in range(10):
            response = client.post(
                "/api/login",
                headers=XHR,
                json={"email": "throttle@example.test", "password": "wrong password"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "throttle@example.test", "password": password},
        )
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "900"


def test_admin_security_status_reports_hardening_without_secrets(tmp_path):
    app = create_app(str(tmp_path / "security-status.db"))
    password = "Administrator secure password 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "status-admin@example.test", "Администратор", make_password_hash(password)),
            )
        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "status-admin@example.test", "password": password},
        )
        assert login.status_code == 200
        status = client.get("/api/admin/security-status")
        assert status.status_code == 200
        data = status.json()
        assert data["password_hash"] == "argon2id"
        assert data["admin_session_minutes"] == 30
        assert data["admin_mfa_mode"] in {"off", "email", "totp"}
        assert data["admin_mfa_strength"] in {"off", "email OTP", "app-based TOTP"}
        assert set(data) == {
            "security_profile", "admin_mfa_mode", "admin_mfa_enabled",
            "admin_mfa_strength", "admin_session_minutes", "admin_idle_minutes",
            "user_idle_hours", "password_hash", "secure_cookie",
            "production_runtime", "api_docs_enabled",
        }
        assert data["security_profile"] in {"standard", "high"}
        assert data["admin_idle_minutes"] == 15
        assert data["user_idle_hours"] == 12
        assert data["password_hash"] == "argon2id"
        serialized = str(data).casefold()
        assert "token_hash" not in serialized
        assert "secret" not in serialized
        assert "credential" not in serialized


def test_production_refuses_email_mfa_without_smtp(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.delenv("OPYT50_SMTP_HOST", raising=False)
    monkeypatch.delenv("OPYT50_MAIL_FROM", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app(str(tmp_path / "unsafe-production.db"))
    with pytest.raises(RuntimeError, match="admin email MFA requires configured SMTP"):
        with TestClient(app):
            pass



def test_admin_totp_mfa_requires_authenticator_code_before_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "totp")
    totp_secret = pyotp.random_base32()
    monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", totp_secret)
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-totp.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "totp-admin@example.test", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "totp-admin@example.test", "password": password},
        )
        assert login.status_code == 200, login.text
        payload = login.json()
        assert payload["mfa_required"] is True
        assert payload["mfa_method"] == "totp"
        assert payload["code_length"] == 6
        assert "debug_code" not in payload
        assert "set-cookie" not in login.headers
        assert client.get("/api/me").status_code == 401

        wrong = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": "000000"},
        )
        assert wrong.status_code == 401
        assert client.get("/api/me").status_code == 401

        code = pyotp.TOTP(totp_secret, digits=6, interval=30).now()
        verified = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": code},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["user"]["role"] == "admin"
        assert client.get("/api/me").status_code == 200

        with database(app.state.db_path) as db:
            events = db.execute(
                "SELECT event_type,detail FROM security_events ORDER BY created_at"
            ).fetchall()
            serialized = "\n".join(str(dict(row)) for row in events)
            assert "admin_totp_challenge_issued" in serialized
            assert code not in serialized
            assert totp_secret not in serialized


def test_production_requires_admin_mfa(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app(str(tmp_path / "no-admin-mfa.db"))
    with pytest.raises(RuntimeError, match="administrator MFA must be enabled"):
        with TestClient(app):
            pass


def test_production_rejects_invalid_totp_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "totp")
    monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", "not-valid-base32-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app(str(tmp_path / "bad-totp.db"))
    with pytest.raises(RuntimeError, match="TOTP secret"):
        with TestClient(app):
            pass



def test_candidate_session_expires_after_idle_timeout(tmp_path):
    app = create_app(str(tmp_path / "candidate-idle.db"))
    password = "Candidate idle timeout password 2026"
    with TestClient(app) as client:
        registration = client.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Кандидат",
                "email": "candidate-idle@example.test",
                "password": password,
            },
        )
        assert registration.status_code == 201, registration.text
        assert client.get("/api/me").status_code == 200

        with database(app.state.db_path) as db:
            row = db.execute(
                """SELECT s.token_hash FROM sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE u.email=?""",
                ("candidate-idle@example.test",),
            ).fetchone()
            old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
            db.execute(
                "UPDATE session_activity SET last_seen_at=? WHERE token_hash=?",
                (old, row["token_hash"]),
            )

        expired = client.get("/api/me")
        assert expired.status_code == 401
        assert "бездействия" in expired.json()["detail"]

        with database(app.state.db_path) as db:
            count = db.execute(
                """SELECT COUNT(*) FROM sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE u.email=?""",
                ("candidate-idle@example.test",),
            ).fetchone()[0]
            assert count == 0


def test_admin_session_expires_after_fifteen_minutes_idle(tmp_path):
    app = create_app(str(tmp_path / "admin-idle.db"))
    password = "Administrator idle timeout password 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "admin-idle@example.test", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "admin-idle@example.test", "password": password},
        )
        assert login.status_code == 200, login.text
        assert client.get("/api/me").status_code == 200

        with database(app.state.db_path) as db:
            row = db.execute(
                """SELECT s.token_hash FROM sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE u.email=?""",
                ("admin-idle@example.test",),
            ).fetchone()
            old = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
            db.execute(
                "UPDATE session_activity SET last_seen_at=? WHERE token_hash=?",
                (old, row["token_hash"]),
            )

        expired = client.get("/api/me")
        assert expired.status_code == 401

        with database(app.state.db_path) as db:
            events = db.execute(
                """SELECT event_type,detail FROM security_events
                   WHERE user_id=(SELECT id FROM users WHERE email=?)
                   ORDER BY created_at DESC""",
                ("admin-idle@example.test",),
            ).fetchall()
            assert any(row["event_type"] == "session_idle_expired" for row in events)


def test_authenticated_activity_refreshes_last_seen_after_touch_interval(tmp_path):
    app = create_app(str(tmp_path / "session-touch.db"))
    with TestClient(app) as client:
        response = client.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Активный кандидат",
                "email": "touch@example.test",
                "password": "Candidate touch password 2026",
            },
        )
        assert response.status_code == 201, response.text

        with database(app.state.db_path) as db:
            row = db.execute(
                """SELECT s.token_hash FROM sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE u.email=?""",
                ("touch@example.test",),
            ).fetchone()
            old_dt = datetime.now(timezone.utc) - timedelta(minutes=2)
            db.execute(
                "UPDATE session_activity SET last_seen_at=? WHERE token_hash=?",
                (old_dt.isoformat(), row["token_hash"]),
            )

        assert client.get("/api/me").status_code == 200

        with database(app.state.db_path) as db:
            refreshed = db.execute(
                "SELECT last_seen_at FROM session_activity WHERE token_hash=?",
                (row["token_hash"],),
            ).fetchone()["last_seen_at"]
        refreshed_dt = datetime.fromisoformat(refreshed)
        if refreshed_dt.tzinfo is None:
            refreshed_dt = refreshed_dt.replace(tzinfo=timezone.utc)
        assert refreshed_dt > old_dt



def test_login_failure_throttle_persists_across_app_instances(tmp_path):
    db_path = str(tmp_path / "shared-throttle.db")
    password = "Persistent throttle password 2026"
    app1 = create_app(db_path)

    with TestClient(app1) as client:
        with database(app1.state.db_path) as db:
            cursor = db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("candidate", "persistent-throttle@example.test", "Кандидат", make_password_hash(password)),
            )
            db.execute("INSERT INTO candidate_profiles(user_id) VALUES(?)", (cursor.lastrowid,))

        for _ in range(10):
            response = client.post(
                "/api/login",
                headers=XHR,
                json={"email": "persistent-throttle@example.test", "password": "wrong password"},
            )
            assert response.status_code == 401

    # A new FastAPI instance has empty process memory but shares the database.
    # The correct password must still be throttled until the fixed window ends.
    app2 = create_app(db_path)
    with TestClient(app2) as client:
        blocked = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "persistent-throttle@example.test", "password": password},
        )
        assert blocked.status_code == 429
        assert "retry-after" in blocked.headers


def test_route_rate_limit_state_is_hashed_and_contains_no_raw_ip_or_email(tmp_path):
    app = create_app(str(tmp_path / "hashed-rate-limit.db"))
    with TestClient(app) as client:
        for index in range(3):
            response = client.post(
                "/api/login",
                headers=XHR,
                json={
                    "email": f"unknown-{index}@example.test",
                    "password": "not the right password",
                },
            )
            assert response.status_code == 401

        with database(app.state.db_path) as db:
            rows = db.execute(
                "SELECT rate_key FROM security_rate_limits"
            ).fetchall()
        assert rows
        serialized = "\n".join(row["rate_key"] for row in rows)
        assert "example.test" not in serialized
        assert "testclient" not in serialized
        assert all(len(row["rate_key"]) == 64 for row in rows)



def test_high_security_profile_rejects_email_admin_mfa(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_SECURITY_PROFILE", "high")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "noreply@example.test")
    monkeypatch.setenv("OPYT50_ALLOWED_HOSTS", "stazhno.ru")
    monkeypatch.setenv("DATABASE_URL", "postgresql://ci@localhost/stazhno")
    monkeypatch.setenv("OPYT50_DB_SSLMODE", "verify-full")

    app = create_app(str(tmp_path / "high-email-mfa.db"))
    with pytest.raises(RuntimeError, match="requires TOTP"):
        with TestClient(app):
            pass


def test_high_security_profile_requires_host_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_SECURITY_PROFILE", "high")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "totp")
    monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", pyotp.random_base32())
    monkeypatch.delenv("OPYT50_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ci@localhost/stazhno")
    monkeypatch.setenv("OPYT50_DB_SSLMODE", "verify-full")

    app = create_app(str(tmp_path / "high-hosts.db"))
    with pytest.raises(RuntimeError, match="Host allowlist"):
        with TestClient(app):
            pass


def test_high_security_profile_requires_verify_full_database_tls(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_SECURITY_PROFILE", "high")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "totp")
    monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", pyotp.random_base32())
    monkeypatch.setenv("OPYT50_ALLOWED_HOSTS", "stazhno.ru")
    monkeypatch.setenv("DATABASE_URL", "postgresql://ci@localhost/stazhno")
    monkeypatch.setenv("OPYT50_DB_SSLMODE", "require")

    app = create_app(str(tmp_path / "high-db-tls.db"))
    with pytest.raises(RuntimeError, match="verify-full"):
        with TestClient(app):
            pass


def test_admin_can_send_smtp_test_email_to_own_address(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "smtp-test-email.db"))
    password = "Administrator secure password 2026"
    captured = {}

    def fake_send_email(recipient, subject, body):
        captured["recipient"] = recipient
        captured["subject"] = subject
        captured["body"] = body
        return True

    monkeypatch.setattr("app.email_delivery.send_email", fake_send_email)

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "admin@stazhno.ru", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "admin@stazhno.ru", "password": password},
        )
        assert login.status_code == 200, login.text

        response = client.post("/api/admin/smtp/test-email", headers=XHR)
        assert response.status_code == 200, response.text
        assert captured["recipient"] == "admin@stazhno.ru"
        assert captured["subject"] == "Проверка почты СТАЖНО"

        with database(app.state.db_path) as db:
            event = db.execute(
                """SELECT detail FROM security_events
                   WHERE event_type='admin_smtp_test_email'
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
            assert event is not None
            assert event["detail"] == "sent=1"


def test_smtp_test_email_reports_delivery_failure_without_leaking_secret(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "smtp-test-email-fail.db"))
    password = "Administrator secure password 2026"
    monkeypatch.setattr("app.email_delivery.send_email", lambda *args, **kwargs: False)

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "admin@stazhno.ru", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "admin@stazhno.ru", "password": password},
        )
        assert login.status_code == 200, login.text

        response = client.post("/api/admin/smtp/test-email", headers=XHR)
        assert response.status_code == 503
        assert "парол" not in response.text.casefold()



def test_admin_security_overview_is_safe_and_operational(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv(
        "OPYT50_PUBLIC_URL",
        "https://arromanov1985-opyt50-platform-fdd8.twc1.net",
    )
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.setenv("OPYT50_DB_SSLMODE", "require")
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "noreply@example.test")
    app = create_app(str(tmp_path / "security-overview.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            cursor = db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "overview-admin@example.test", "Администратор", make_password_hash(password)),
            )
            admin_id = cursor.lastrowid
            db.execute(
                "INSERT INTO account_controls(user_id,email_verified) VALUES(?,1)",
                (admin_id,),
            )
            now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            for event_type in (
                "login_password_failed",
                "new_device_login",
                "password_reset_completed",
                "admin_passkey_registered",
            ):
                db.execute(
                    """INSERT INTO security_events(event_key,user_id,event_type,detail,created_at)
                       VALUES(?,?,?,?,?)""",
                    (f"overview-{event_type}", admin_id, event_type, "", now),
                )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "overview-admin@example.test", "password": password},
        )
        assert login.status_code == 200, login.text

        response = client.get("/api/admin/security-overview")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["temporary_origin"] is True
        assert data["active_sessions"] == 1
        assert data["events_24h"] == {
            "failed_auth": 1,
            "new_devices": 1,
            "password_changes": 1,
            "passkey_changes": 1,
        }
        checks = {item["key"]: item for item in data["checks"]}
        assert checks["email"]["status"] == "ok"
        assert checks["mfa"]["status"] == "warning"
        assert checks["passkey"]["status"] == "info"
        assert checks["database_tls"]["status"] == "warning"
        assert checks["cookie"]["status"] == "ok"
        serialized = str(data).casefold()
        for forbidden in ("smtp_password", "totp_secret", "token_hash", "credential_id"):
            assert forbidden not in serialized
