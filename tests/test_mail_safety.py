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


def test_legacy_queue_without_recipient_mapping_keeps_compatibility(
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
            from app.mail_queue import enqueue_workflow_job
            enqueue_workflow_job(db, inserted.lastrowid, "invitation", redacted=False)
        assert count_recipients(app) == 0
        assert process_due_workflow_mail(app.state.db_path)["accepted"] == 1
        assert len(out) == 1


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
