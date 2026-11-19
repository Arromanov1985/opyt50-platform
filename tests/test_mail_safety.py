"""Protect queued notifications from stale delivery and account state changes."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.mail_queue import process_due_workflow_mail
from app.release02 import enqueue_notice


def setup_mail(monkeypatch):
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "noreply@example.invalid")
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "0")
    outgoing = []
    monkeypatch.setattr(
        "app.mail_queue.send_email",
        lambda *args: outgoing.append(args) or True,
    )
    return outgoing


def create_real_job(app):
    with database(app.state.db_path) as db:
        u = db.execute(
            """INSERT INTO users(email,role,name,password_hash)
               VALUES('recipient@demo.example','candidate','Test','fake-hash')"""
        )
        user_id = u.lastrowid
        enqueue_notice(db, user_id, "invitation", "Тестовое приглашение", "Событие")
        job = db.execute(
            "SELECT outbox_id FROM email_delivery_jobs ORDER BY outbox_id DESC LIMIT 1"
        ).fetchone()
        assert job is not None
        return user_id, job["outbox_id"]


def queue_row(app):
    with database(app.state.db_path) as db:
        return dict(db.execute(
            "SELECT state,last_error_code,attempts FROM email_delivery_jobs"
        ).fetchone())


def count_recipients(app):
    with database(app.state.db_path) as db:
        return int(db.execute(
            "SELECT COUNT(*) FROM email_delivery_recipients"
        ).fetchone()[0])


def test_active_recipient_receives_new_notification(tmp_path: Path, monkeypatch):
    out = setup_mail(monkeypatch)
    app = create_app(str(tmp_path / "active.db"))
    with TestClient(app):
        user_id, outbox_id = create_real_job(app)
        with database(app.state.db_path) as db:
            mapped = db.execute(
                "SELECT user_id FROM email_delivery_recipients WHERE outbox_id=?",
                (outbox_id,),
            ).fetchone()
            assert mapped["user_id"] == user_id
        assert process_due_workflow_mail(app.state.db_path)["accepted"] == 1
        assert len(out) == 1
        assert out[0][0] == "recipient@demo.example"
        assert queue_row(app)["state"] == "accepted"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("disabled", "recipient_unavailable"),
        ("email_changed", "recipient_unavailable"),
        ("deleted", "recipient_unavailable"),
        ("outdated", "stale_notice"),
        ("invalid_time", "invalid_created_at"),
    ],
)
def test_queue_does_not_send_to_unavailable_recipient_or_stale_event(
    tmp_path: Path, monkeypatch, mutation: str, reason: str,
):
    out = setup_mail(monkeypatch)
    app = create_app(str(tmp_path / f"{mutation}.db"))
    with TestClient(app):
        user_id, _ = create_real_job(app)
        with database(app.state.db_path) as db:
            if mutation == "disabled":
                db.execute(
                    "INSERT INTO account_controls(user_id,status) VALUES(?,'disabled')",
                    (user_id,),
                )
            elif mutation == "email_changed":
                db.execute(
                    "UPDATE users SET email='updated@demo.example' WHERE id=?",
                    (user_id,),
                )
            elif mutation == "deleted":
                db.execute("DELETE FROM users WHERE id=?", (user_id,))
            elif mutation == "outdated":
                old = (datetime.now(timezone.utc) - timedelta(hours=74)).isoformat()
                db.execute("UPDATE email_delivery_jobs SET created_at=?", (old,))
            elif mutation == "invalid_time":
                db.execute("UPDATE email_delivery_jobs SET created_at='bad-timestamp'")
        result = process_due_workflow_mail(app.state.db_path)
        assert result["processed"] == result["exhausted"] == 1
        assert result["accepted"] == 0
        assert not out
        state = queue_row(app)
        assert state["state"] == "exhausted"
        assert state["last_error_code"] == reason
        assert process_due_workflow_mail(app.state.db_path)["processed"] == 0
        assert count_recipients(app) == 1


def test_legacy_queue_without_recipient_mapping_is_quarantined(
    tmp_path: Path, monkeypatch,
):
    out = setup_mail(monkeypatch)
    app = create_app(str(tmp_path / "legacy.db"))
    with TestClient(app):
        with database(app.state.db_path) as db:
            inserted = db.execute(
                "INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
                ("old@demo.example", "invitation", "Old", "Still pending"),
            )
            # Simulate a pre-upgrade job without any user mapping.
            db.execute(
                """INSERT INTO email_delivery_jobs
                   (outbox_id,state,attempts,next_attempt_at,created_at)
                   VALUES(?,'pending',0,?,?)""",
                (inserted.lastrowid, datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            )
        assert count_recipients(app) == 0
        assert process_due_workflow_mail(app.state.db_path)["exhausted"] == 1
        assert queue_row(app)["last_error_code"] == "unmapped_recipient"
        assert not out


def test_new_unmapped_workflow_job_is_rejected(tmp_path: Path, monkeypatch):
    setup_mail(monkeypatch)
    app = create_app(str(tmp_path / "new-unmapped.db"))
    with TestClient(app):
        with database(app.state.db_path) as db:
            inserted = db.execute(
                "INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
                ("unknown@demo.example", "invitation", "Test", "Test"),
            )
            from app.mail_queue import enqueue_workflow_job
            assert not enqueue_workflow_job(
                db, inserted.lastrowid, "invitation", redacted=False
            )
            assert db.execute("SELECT COUNT(*) FROM email_delivery_jobs").fetchone()[0] == 0


def test_privacy_request_prevents_new_workflow_outbox_and_job(tmp_path: Path, monkeypatch):
    out = setup_mail(monkeypatch)
    app = create_app(str(tmp_path / "privacy-enqueue.db"))
    with TestClient(app):
        with database(app.state.db_path) as db:
            user_id = db.execute(
                """INSERT INTO users(email,role,name,password_hash)
                   VALUES('privacy@demo.example','candidate','Test','fake-hash')"""
            ).lastrowid
            db.execute(
                """INSERT INTO privacy_rights_requests
                   (request_key,user_id,kind,status,submitted_at,updated_at)
                   VALUES(?,?,'stop_processing','received',?,?)""",
                ("privacy-stop-before-enqueue", user_id,
                 datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            )
            enqueue_notice(db, user_id, "invitation", "Test", "Do not send")
            assert db.execute("SELECT COUNT(*) FROM email_delivery_jobs").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 0
        assert process_due_workflow_mail(app.state.db_path)["processed"] == 0
        assert not out


def test_queue_uses_additive_schema_across_restarts(tmp_path: Path, monkeypatch):
    out = setup_mail(monkeypatch)
    db_path = str(tmp_path / "restart.db")
    app = create_app(db_path)
    with TestClient(app):
        create_real_job(app)
        assert count_recipients(app) == 1
    new_app = create_app(db_path)
    with TestClient(new_app):
        assert count_recipients(new_app) == 1
        assert process_due_workflow_mail(db_path)["accepted"] == 1
        assert len(out) == 1

def test_administrator_sees_suppressed_counts_not_addresses(tmp_path: Path, monkeypatch):
    from app.security import make_password_hash

    setup_mail(monkeypatch)
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    app = create_app(str(tmp_path / "counts.db"))
    with TestClient(app) as client:
        user_id, _ = create_real_job(app)
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO account_controls(user_id,status) VALUES(?,'disabled')",
                (user_id,),
            )
            db.execute(
                "INSERT INTO users(email,role,name,password_hash) VALUES(?,?,?,?)",
                (
                    "review-admin@demo.example", "admin", "Review Admin",
                    make_password_hash("StrongPass2026!"),
                ),
            )
        assert process_due_workflow_mail(app.state.db_path)["exhausted"] == 1
        assert client.get("/api/admin/mail-diagnostics").status_code == 401
        login = client.post(
            "/api/login", headers={"X-Requested-With": "OPYT50"},
            json={"email": "review-admin@demo.example", "password": "StrongPass2026!"},
        )
        assert login.status_code == 200, login.text
        report = client.get("/api/admin/mail-diagnostics")
        assert report.status_code == 200, report.text
        queue = report.json()["retry_queue"]
        assert queue["suppressed"] == 1
        assert queue["exhausted"] == 0
        assert queue["accepted"] == 0
        assert "recipient@demo.example" not in report.text
        assert "Событие" not in report.text



@pytest.mark.parametrize("kind,status,should_block", [
    ("deletion", "received", True),
    ("deletion", "in_review", True),
    ("deletion", "completed", True),
    ("stop_processing", "received", True),
    ("stop_processing", "in_review", True),
    ("stop_processing", "completed", True),
    ("deletion", "declined", False),
    ("access", "received", False),
])
def test_workflow_mail_respects_data_subject_privacy_requests(
    tmp_path: Path, monkeypatch, kind, status, should_block,
):
    sent = setup_mail(monkeypatch)
    app = create_app(str(tmp_path / f"privacy-{kind}-{status}.db"))
    with TestClient(app):
        user_id, _ = create_real_job(app)
        with database(app.state.db_path) as db:
            db.execute(
                """INSERT INTO privacy_rights_requests
                   (request_key,user_id,kind,status,submitted_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                (f"{kind}-{status}-request", user_id, kind, status,
                 "2026-11-19T00:00:00+00:00", "2026-11-19T00:00:00+00:00"),
            )
        result = process_due_workflow_mail(app.state.db_path)
        if should_block:
            assert result["exhausted"] == 1
            assert result["accepted"] == 0
            assert not sent
            assert queue_row(app)["last_error_code"] == "privacy_request"
            assert process_due_workflow_mail(app.state.db_path)["processed"] == 0
        else:
            assert result["accepted"] == 1
            assert len(sent) == 1


def test_privacy_suppressed_workflow_count_is_non_identifying_in_admin_report(tmp_path, monkeypatch):
    from app.security import make_password_hash

    sent = setup_mail(monkeypatch)
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    app = create_app(str(tmp_path / "suppressed.db"))
    with TestClient(app) as client:
        user_id, _ = create_real_job(app)
        with database(app.state.db_path) as db:
            db.execute(
                """INSERT INTO privacy_rights_requests
                   (request_key,user_id,kind,status,submitted_at,updated_at)
                   VALUES(?,?,'deletion','received',?,?)""",
                ("suppress-me-privacy-test", user_id,
                 "2026-11-19T00:00:00+00:00", "2026-11-19T00:00:00+00:00"),
            )
            db.execute(
                "INSERT INTO users(email,role,name,password_hash) VALUES(?,?,?,?)",
                ("privacy-mail-admin@example.invalid","admin","Admin",
                 make_password_hash("StrongPass2026!")),
            )
        assert process_due_workflow_mail(app.state.db_path)["exhausted"] == 1
        assert not sent
        assert client.post("/api/login",
            headers={"X-Requested-With":"OPYT50"},
            json={"email":"privacy-mail-admin@example.invalid",
                  "password":"StrongPass2026!"}).status_code == 200
        report = client.get("/api/admin/mail-diagnostics")
        assert report.status_code == 200
        assert report.json()["retry_queue"]["suppressed"] == 1
        assert report.json()["retry_queue"]["exhausted"] == 0
        assert "recipient@demo.example" not in report.text
