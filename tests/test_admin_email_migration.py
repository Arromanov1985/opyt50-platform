"""Production administrator email migration regression tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db import database, init_db
from app.release02 import (
    LEGACY_ADMIN_EMAIL,
    PRODUCTION_ADMIN_EMAIL,
    init_release02,
    migrate_legacy_admin_email,
)
from app.security import make_password_hash


def prepare_schema(path: str) -> None:
    init_db(path)
    init_release02(path)


def test_legacy_admin_email_migrates_without_changing_identity(tmp_path: Path):
    path = str(tmp_path / "admin-email.db")
    prepare_schema(path)

    with database(path) as db:
        user_id = db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            (
                "admin",
                LEGACY_ADMIN_EMAIL,
                "Администратор",
                make_password_hash("Administrator secure password 2026"),
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO account_controls(user_id,email_verified,status) VALUES(?,1,'active')",
            (user_id,),
        )
        db.execute(
            "INSERT INTO email_tokens(token_hash,user_id,purpose,expires_at) VALUES(?,?,?,?)",
            (
                "legacy-reset-token-hash",
                user_id,
                "reset",
                (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
            (
                "legacy-session-hash",
                user_id,
                (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            ),
        )
        db.execute(
            """INSERT INTO admin_mfa_challenges(
                   challenge_key,user_id,code_hash,expires_at,attempts,created_at
               ) VALUES(?,?,?,?,0,?)""",
            (
                "legacy-mfa-challenge",
                user_id,
                "totp-v1",
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.execute(
            """INSERT INTO admin_webauthn_credentials(
                   credential_id,user_id,public_key,sign_count,label,transports,
                   credential_device_type,backed_up,created_at,last_used_at
               ) VALUES(?,?,?,?,?,?,?,?,?,NULL)""",
            (
                "AQID",
                user_id,
                "fake-public-key",
                3,
                "Windows Hello",
                '["internal"]',
                "multi_device",
                1,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    # Re-running the normal release initializer performs the one-time migration.
    init_release02(path)

    with database(path) as db:
        admin = db.execute(
            "SELECT id,email,role FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        assert admin["id"] == user_id
        assert admin["email"] == PRODUCTION_ADMIN_EMAIL
        assert admin["role"] == "admin"
        assert db.execute(
            "SELECT COUNT(*) FROM users WHERE email=?",
            (LEGACY_ADMIN_EMAIL,),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT email_verified FROM account_controls WHERE user_id=?",
            (user_id,),
        ).fetchone()["email_verified"] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM email_tokens WHERE user_id=?",
            (user_id,),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=?",
            (user_id,),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM admin_mfa_challenges WHERE user_id=?",
            (user_id,),
        ).fetchone()[0] == 0
        passkey = db.execute(
            "SELECT label,sign_count FROM admin_webauthn_credentials WHERE user_id=?",
            (user_id,),
        ).fetchone()
        assert passkey["label"] == "Windows Hello"
        assert passkey["sign_count"] == 3
        assert db.execute(
            """SELECT COUNT(*) FROM security_events
               WHERE user_id=? AND event_type='admin_email_migrated'""",
            (user_id,),
        ).fetchone()[0] == 1

    # Idempotent after the address has already been changed.
    with database(path) as db:
        assert migrate_legacy_admin_email(db) is False


def test_admin_email_migration_refuses_identity_collision(tmp_path: Path):
    path = str(tmp_path / "admin-email-collision.db")
    prepare_schema(path)

    with database(path) as db:
        db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            ("admin", LEGACY_ADMIN_EMAIL, "Старый администратор", make_password_hash("Password one secure 2026")),
        )
        db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            ("candidate", PRODUCTION_ADMIN_EMAIL, "Другой пользователь", make_password_hash("Password two secure 2026")),
        )
        with pytest.raises(RuntimeError, match="already used"):
            migrate_legacy_admin_email(db)
