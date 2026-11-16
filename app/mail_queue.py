"""Durable, bounded retries for non-sensitive workflow notification emails.

Only events in WORKFLOW_EVENTS are eligible. Security, MFA, password-reset and
verification emails are deliberately NOT queued, because token expiry and
redacted storage make their automatic replay unsafe.

A database claim is committed before SMTP; acceptance is recorded afterwards.
This is at-least-once, NOT exactly-once: a crash after SMTP acceptance but
before recording success can produce a duplicate after a lease expires.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from .db import database
from .email_delivery import delivery_mode, send_email

logger = logging.getLogger(__name__)

WORKFLOW_EVENTS = frozenset({
    "new_application", "invitation", "invitation_response",
    "contact_opened", "application_status",
})
MAX_ATTEMPTS = 4  # First attempt plus at most three automatic retries.
RETRY_DELAYS = (30, 120, 600)  # Seconds following failures 1, 2 and 3.
LEASE_SECONDS = 120
POLL_SECONDS = 5
BATCH_LIMIT = 8
# Outdated workflow alerts must not be mailed days after a long SMTP outage.
MAX_NOTICE_AGE = timedelta(hours=72)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def enqueue_workflow_job(
    db, outbox_id: int, event: str, *, redacted: bool,
    recipient_user_id: int | None = None,
) -> bool:
    """Enqueue in the SAME transaction as the business operation and outbox.

    No existing historic outbox messages are imported; a new deployment must
    never replay emails previously attempted by earlier releases.
    """
    if event not in WORKFLOW_EVENTS or redacted:
        return False
    instant = _stamp(_now())
    db.execute(
        """INSERT INTO email_delivery_jobs(
               outbox_id,state,attempts,next_attempt_at,created_at
           ) VALUES(?, 'pending', 0, ?, ?)""",
        (outbox_id, instant, instant),
    )
    if recipient_user_id is not None:
        # A separate mapping table is additive for existing 0.5.5 queues.
        db.execute(
            "INSERT INTO email_delivery_recipients(outbox_id,user_id) VALUES(?,?)",
            (outbox_id, recipient_user_id),
        )
    return True


def _claim_next(db_path: str, now: datetime):
    stamp = _stamp(now)
    until = _stamp(now + timedelta(seconds=LEASE_SECONDS))
    with database(db_path) as db:
        # A process may die during its final attempt. A timed-out final
        # lease is exhausted, not sent a fifth time.
        db.execute(
            """UPDATE email_delivery_jobs
               SET state='exhausted', last_error_code='lease_expired',
                   lease_token=NULL, leased_until=NULL
               WHERE state='leased' AND attempts>=? AND leased_until<=?""",
            (MAX_ATTEMPTS, stamp),
        )
        # The conditional UPDATE is the cross-SQLite/PostgreSQL claim lock.
        # Competing workers can see a candidate, but only one obtains it.
        rows = db.execute(
            """SELECT q.outbox_id,o.to_email,o.subject,o.body,q.attempts,q.created_at
               FROM email_delivery_jobs q
               JOIN email_outbox o ON o.id=q.outbox_id
               WHERE q.attempts<?
                 AND ((q.state='pending' AND q.next_attempt_at<=?)
                   OR (q.state='leased' AND q.leased_until<=?))
               ORDER BY q.outbox_id LIMIT 20""",
            (MAX_ATTEMPTS, stamp, stamp),
        ).fetchall()
        for item in rows:
            token = secrets.token_hex(16)
            changed = db.execute(
                """UPDATE email_delivery_jobs
                   SET state='leased', attempts=attempts+1, lease_token=?,
                       leased_until=?
                   WHERE outbox_id=? AND attempts<?
                     AND ((state='pending' AND next_attempt_at<=?)
                       OR (state='leased' AND leased_until<=?))""",
                (token, until, item["outbox_id"], MAX_ATTEMPTS, stamp, stamp),
            )
            if changed.rowcount == 1:
                db.commit()  # Commit BEFORE an external SMTP side effect.
                return {
                    "id": item["outbox_id"], "recipient": item["to_email"],
                    "subject": item["subject"], "body": item["body"],
                    "attempt": int(item["attempts"]) + 1, "token": token,
                    "created_at": item["created_at"],
                }
    return None


def _delivery_block_reason(db_path: str, item, now: datetime) -> str | None:
    """Suppress out-of-date notices or mail destined for disabled/deleted users.

    Unmapped 0.5.5 jobs stay eligible until the age limit. All newly
    generated workflow notices have a stable recipient identity.
    """
    try:
        created = datetime.fromisoformat(str(item["created_at"]))
        if created.tzinfo is None:
            return "invalid_created_at"
        if now - created.astimezone(timezone.utc) >= MAX_NOTICE_AGE:
            return "stale_notice"
    except (ValueError, TypeError):
        return "invalid_created_at"

    with database(db_path) as db:
        entry = db.execute(
            """SELECT t.user_id,u.email,COALESCE(c.status,'active') AS account_status
               FROM email_delivery_recipients t
               LEFT JOIN users u ON u.id=t.user_id
               LEFT JOIN account_controls c ON c.user_id=u.id
               WHERE t.outbox_id=?""",
            (item["id"],),
        ).fetchone()
    if entry is None:  # Previously queued jobs have no recipient mapping.
        return None
    if (entry["user_id"] is None or entry["email"] != item["recipient"]
            or entry["account_status"] != "active"):
        return "recipient_unavailable"
    return None


def _suppress(db_path: str, item, reason: str) -> bool:
    """Complete this lease without SMTP; only known non-sensitive codes."""
    assert reason in ("stale_notice", "invalid_created_at", "recipient_unavailable")
    with database(db_path) as db:
        updated = db.execute(
            """UPDATE email_delivery_jobs
               SET state='exhausted', last_error_code=?,
                   lease_token=NULL, leased_until=NULL
               WHERE outbox_id=? AND state='leased' AND lease_token=?""",
            (reason, item["id"], item["token"]),
        )
    return updated.rowcount == 1


def _finish(db_path: str, item, accepted: bool, now: datetime) -> str:
    attempt = item["attempt"]
    if accepted:
        state, due, accepted_at, error = "accepted", _stamp(now), _stamp(now), ""
    elif attempt >= MAX_ATTEMPTS:
        state, due, accepted_at, error = "exhausted", _stamp(now), None, "smtp_not_accepted"
    else:
        state = "pending"
        due = _stamp(now + timedelta(seconds=RETRY_DELAYS[attempt - 1]))
        accepted_at, error = None, "smtp_not_accepted"
    with database(db_path) as db:
        result = db.execute(
            """UPDATE email_delivery_jobs
               SET state=?, next_attempt_at=?, accepted_at=?,
                   last_error_code=?, lease_token=NULL, leased_until=NULL
               WHERE outbox_id=? AND state='leased' AND lease_token=?""",
            (state, due, accepted_at, error, item["id"], item["token"]),
        )
        db.commit()
    if result.rowcount != 1:
        # A recovered lease may have been claimed by another worker. Do not
        # overwrite the new owner's result or emit sensitive message details.
        logger.warning("Mail claim expired before result was recorded")
        return "lease_lost"
    return state


def process_due_workflow_mail(
    db_path: str, *, now: datetime | None = None, limit: int = BATCH_LIMIT,
) -> dict[str, int]:
    """Process at most 'limit' committed jobs, with no customer data in logs."""
    totals = {"processed": 0, "accepted": 0, "pending": 0, "exhausted": 0}
    if delivery_mode() != "smtp":
        return totals  # Preserve attempts until SMTP is actually configured.
    clock = now or _now()
    for _ in range(max(0, min(int(limit), BATCH_LIMIT))):
        item = _claim_next(db_path, clock)
        if item is None:
            break
        reason = _delivery_block_reason(db_path, item, clock)
        if reason is not None:
            if _suppress(db_path, item, reason):
                totals["processed"] += 1
                totals["exhausted"] += 1
            continue
        try:
            accepted = bool(send_email(item["recipient"], item["subject"], item["body"]))
        except Exception as exc:
            # The transport is expected to return False, but a monkeypatch or
            # unexpected error must still release the lease for a later retry.
            logger.error("Mail transport failed (%s)", type(exc).__name__)
            accepted = False
        outcome = _finish(db_path, item, accepted, clock)
        totals["processed"] += 1
        if outcome in totals:
            totals[outcome] += 1
    return totals


async def workflow_mail_worker(db_path: str) -> None:
    """Poll a shared database safely across multiple running app instances."""
    await asyncio.sleep(2)
    while True:
        try:
            await asyncio.to_thread(process_due_workflow_mail, db_path)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Mail worker iteration failed (%s)", type(exc).__name__)
        await asyncio.sleep(POLL_SECONDS)
