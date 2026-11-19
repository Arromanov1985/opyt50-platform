"""Operator-only external-system review log.

Does not connect to a backup provider or verify a deletion. Stored statuses
are manual attestations, not evidence of real-world fulfilment.
"""
from __future__ import annotations
from datetime import datetime, timezone
import secrets

SYSTEMS = (
    ("database_backups", "Резервные копии базы данных"),
    ("hosting_logs", "Журналы хостинга и инфраструктуры"),
    ("smtp_provider", "Письма и данные у почтового провайдера"),
    ("workflow_mail_queue", "Очередь и отложенная отправка писем"),
    ("third_party_recipients", "Получатели ранее раскрытых контактов"),
)
VALID_STATUSES = frozenset({"reviewed", "not_applicable", "followup_required"})
DONE_STATUSES = frozenset({"reviewed", "not_applicable"})


def external_review_status(db, request_key: str) -> dict | None:
    owner = db.execute(
        """SELECT kind,status FROM privacy_rights_requests WHERE request_key=?""",
        (request_key,),
    ).fetchone()
    if owner is None:
        return None
    if owner["kind"] not in {"deletion", "stop_processing"}:
        raise ValueError("External review applies to deletion or cessation requests")
    rows = db.execute(
        """SELECT system_key,status,reviewed_at FROM privacy_external_reviews
           WHERE request_key=?""", (request_key,),
    ).fetchall()
    by_key = {row["system_key"]: row for row in rows}
    checks = [{
        "system_key": key,
        "label": label,
        "status": by_key[key]["status"] if key in by_key else "not_reviewed",
        "reviewed_at": by_key[key]["reviewed_at"] if key in by_key else None,
    } for key, label in SYSTEMS]
    return {
        "request_key": request_key,
        "checks": checks,
        "ready_for_manual_closure": all(c["status"] in DONE_STATUSES for c in checks),
        "provider_live_verification": False,
        "external_actions_performed_automatically": False,
    }


def save_external_review(
    db, request_key: str, admin_id: int, system_key: str, status: str,
) -> dict | None:
    if system_key not in dict(SYSTEMS):
        raise ValueError("Unknown external system")
    if status not in VALID_STATUSES:
        raise ValueError("Unknown review state")
    # Never wave away real infrastructure: only an absence of previously
    # shared contacts can make the third-party recipient section N/A.
    if status == "not_applicable" and system_key != "third_party_recipients":
        raise ValueError("Core external systems cannot be marked not applicable")
    row = db.execute(
        "SELECT kind,status FROM privacy_rights_requests WHERE request_key=?",
        (request_key,),
    ).fetchone()
    if row is None:
        return None
    if row["kind"] not in {"deletion", "stop_processing"}:
        raise ValueError("Only deletion or cessation requests need external review")
    if row["status"] != "in_review":
        raise ValueError("Start review before attesting external systems")
    if status == "not_applicable":
        opened = db.execute(
            """SELECT COUNT(*) FROM invitations i
               JOIN privacy_rights_requests r
                 ON (r.user_id=i.candidate_id OR r.user_id=i.employer_id)
               WHERE r.request_key=? AND i.contact_shared=1""",
            (request_key,),
        ).fetchone()[0]
        if opened:
            raise ValueError("Cannot mark recipients inapplicable after contact disclosure")
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute(
        """INSERT INTO privacy_external_reviews
           (request_key,system_key,status,reviewed_at,reviewed_by)
           VALUES(?,?,?,?,?)
           ON CONFLICT(request_key,system_key) DO UPDATE SET
           status=excluded.status, reviewed_at=excluded.reviewed_at,
           reviewed_by=excluded.reviewed_by""",
        (request_key, system_key, status, stamp, admin_id),
    )
    db.execute(
        """INSERT INTO privacy_external_review_events
           (event_key,request_key,system_key,status,reviewed_at,reviewed_by)
           VALUES(?,?,?,?,?,?)""",
        (secrets.token_urlsafe(16), request_key, system_key, status, stamp, admin_id),
    )
    return external_review_status(db, request_key)
