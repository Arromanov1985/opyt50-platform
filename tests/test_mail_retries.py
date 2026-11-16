"""No-network tests of durable workflow email retries and concurrent claims."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.mail_queue import (
    LEASE_SECONDS, MAX_ATTEMPTS, RETRY_DELAYS, _claim_next,
    enqueue_workflow_job, process_due_workflow_mail,
)
from app.release02 import enqueue_notice


def configured(monkeypatch):
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "noreply@example.invalid")
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "0")


def create_notice(app, event="invitation"):
    with database(app.state.db_path) as db:
        inserted = db.execute(
            "INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
            ("fictional@demo.example", event, "Тестовое событие", "Тестовое сообщение"),
        )
        assert enqueue_workflow_job(
            db, inserted.lastrowid, event, redacted=False,
        ) is True
    return inserted.lastrowid


def job_state(app):
    with database(app.state.db_path) as db:
        return dict(db.execute(
            """SELECT outbox_id,state,attempts,next_attempt_at,
                      lease_token,leased_until,accepted_at,last_error_code
               FROM email_delivery_jobs ORDER BY outbox_id DESC LIMIT 1"""
        ).fetchone())


def future():
    return datetime.now(timezone.utc) + timedelta(seconds=2)


def test_automatic_retry_backoff_and_acceptance(tmp_path: Path, monkeypatch):
    configured(monkeypatch)
    app = create_app(str(tmp_path / "retry.db"))
    responses = [False, True]
    attempted = []

    def smtp(to, subject, body):
        attempted.append((to, subject, body))
        return responses.pop(0)

    monkeypatch.setattr("app.mail_queue.send_email", smtp)
    with TestClient(app):
        create_notice(app)
        start = future()
        first = process_due_workflow_mail(app.state.db_path, now=start)
        assert first == {"processed": 1, "accepted": 0, "pending": 1, "exhausted": 0}
        assert job_state(app)["attempts"] == 1
        assert job_state(app)["last_error_code"] == "smtp_not_accepted"
        early = process_due_workflow_mail(
            app.state.db_path, now=start + timedelta(seconds=RETRY_DELAYS[0] - 1),
        )
        assert early["processed"] == 0
        second = process_due_workflow_mail(
            app.state.db_path, now=start + timedelta(seconds=RETRY_DELAYS[0]),
        )
        assert second["accepted"] == 1 and second["processed"] == 1
        assert job_state(app)["state"] == "accepted"
        assert job_state(app)["attempts"] == 2
        assert job_state(app)["accepted_at"] is not None
        assert len(attempted) == 2
        assert process_due_workflow_mail(
            app.state.db_path, now=start + timedelta(days=1),
        )["processed"] == 0


def test_failed_messages_stop_after_four_attempts(tmp_path: Path, monkeypatch):
    configured(monkeypatch)
    app = create_app(str(tmp_path / "exhausted.db"))
    attempts = []
    monkeypatch.setattr(
        "app.mail_queue.send_email",
        lambda *args: attempts.append(args) or False,
    )
    with TestClient(app):
        create_notice(app)
        current = future()
        for attempt in range(MAX_ATTEMPTS):
            outcome = process_due_workflow_mail(app.state.db_path, now=current)
            assert outcome["processed"] == 1
            if attempt < MAX_ATTEMPTS - 1:
                assert outcome["pending"] == 1
                current += timedelta(seconds=RETRY_DELAYS[attempt])
            else:
                assert outcome["exhausted"] == 1
        assert job_state(app)["state"] == "exhausted"
        assert job_state(app)["attempts"] == MAX_ATTEMPTS
        assert len(attempts) == MAX_ATTEMPTS
        assert process_due_workflow_mail(
            app.state.db_path, now=current + timedelta(days=30),
        )["processed"] == 0


def test_two_workers_cannot_send_same_claim_concurrently(tmp_path: Path, monkeypatch):
    configured(monkeypatch)
    app = create_app(str(tmp_path / "concurrent.db"))
    entered = Event()
    release = Event()
    calls = []

    def slow_smtp(*args):
        calls.append(args)
        entered.set()
        assert release.wait(timeout=5)
        return True

    monkeypatch.setattr("app.mail_queue.send_email", slow_smtp)
    with TestClient(app):
        create_notice(app)
        now = future()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                process_due_workflow_mail, app.state.db_path, now=now,
            )
            assert entered.wait(timeout=5), "First worker did not reach SMTP"
            competitor = process_due_workflow_mail(app.state.db_path, now=now)
            assert competitor["processed"] == 0
            release.set()
            result = first.result(timeout=5)
        assert result["accepted"] == 1
        assert len(calls) == 1
        assert job_state(app)["attempts"] == 1


def test_lease_recovery_and_final_attempt_expiry(tmp_path: Path, monkeypatch):
    configured(monkeypatch)
    app = create_app(str(tmp_path / "leased.db"))
    sent = []
    monkeypatch.setattr(
        "app.mail_queue.send_email",
        lambda *args: sent.append(args) or True,
    )
    with TestClient(app):
        create_notice(app)
        start = future()
        job = _claim_next(app.state.db_path, start)
        assert job and job_state(app)["state"] == "leased"
        assert process_due_workflow_mail(
            app.state.db_path, now=start + timedelta(seconds=LEASE_SECONDS - 1),
        )["processed"] == 0
        recovered = process_due_workflow_mail(
            app.state.db_path, now=start + timedelta(seconds=LEASE_SECONDS + 1),
        )
        assert recovered["accepted"] == 1
        assert job_state(app)["attempts"] == 2
        assert len(sent) == 1

        # An abandoned fourth claim becomes exhausted rather than issuing a
        # fifth SMTP attempt.
        with database(app.state.db_path) as db:
            db.execute(
                """UPDATE email_delivery_jobs
                   SET state='leased', attempts=?, leased_until=?,
                       lease_token='abandoned', accepted_at=NULL
                   WHERE outbox_id=?""",
                (MAX_ATTEMPTS, "2000-01-01T00:00:00+00:00", job["id"]),
            )
        result = process_due_workflow_mail(
            app.state.db_path, now=start + timedelta(days=1),
        )
        assert result["processed"] == 0
        assert job_state(app)["state"] == "exhausted"
        assert len(sent) == 1


def test_no_replay_of_old_outbox_or_token_links(tmp_path: Path, monkeypatch):
    configured(monkeypatch)
    app = create_app(str(tmp_path / "legacy.db"))
    normal_send = []
    queued_send = []
    monkeypatch.setattr(
        "app.release02.send_email",
        lambda *args: normal_send.append(args) or True,
    )
    monkeypatch.setattr(
        "app.mail_queue.send_email",
        lambda *args: queued_send.append(args) or True,
    )
    with TestClient(app):
        with database(app.state.db_path) as db:
            # Existing historical notices were generated before this
            # feature; they must not be mailed again after deployment.
            db.execute(
                "INSERT INTO email_outbox(to_email,event,subject,body) "
                "VALUES(?,?,?,?)",
                ("legacy@demo.example", "invitation", "Old", "Do not replay"),
            )
            user = db.execute(
                """INSERT INTO users(role,email,name,password_hash)
                   VALUES('candidate','user@demo.example','Test','fake-hash')"""
            )
            enqueue_notice(
                db, user.lastrowid, "account_reset",
                "Reset", "A short-lived secret link",
                stored_body="Token intentionally redacted",
            )
        assert len(normal_send) == 1
        assert normal_send[0][2] == "A short-lived secret link"
        assert process_due_workflow_mail(app.state.db_path)["processed"] == 0
        assert queued_send == []
        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM email_delivery_jobs"
            ).fetchone()[0] == 0
            assert db.execute(
                "SELECT body FROM email_outbox WHERE event='account_reset'"
            ).fetchone()["body"] == "Token intentionally redacted"


def test_rolled_back_business_action_cannot_send_email(tmp_path: Path, monkeypatch):
    configured(monkeypatch)
    app = create_app(str(tmp_path / "rolled-back.db"))
    sent = []
    monkeypatch.setattr(
        "app.mail_queue.send_email",
        lambda *args: sent.append(args) or True,
    )
    with TestClient(app):
        with pytest.raises(RuntimeError), database(app.state.db_path) as db:
            row = db.execute(
                "INSERT INTO email_outbox(to_email,event,subject,body) "
                "VALUES('fictional@demo.example','new_application','Test','Body')"
            )
            enqueue_workflow_job(
                db, row.lastrowid, "new_application", redacted=False,
            )
            raise RuntimeError("Business transaction rolled back")
        assert process_due_workflow_mail(app.state.db_path)["processed"] == 0
        assert not sent
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM email_delivery_jobs").fetchone()[0] == 0
