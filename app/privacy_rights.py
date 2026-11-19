"""Data-subject request inbox, separate from marketing and account analytics.

Minimal information is stored: request kind, submitting account, timestamps,
status, and categorical administrative decisions. This is only an intake and
tracking mechanism; it does NOT automatically erase, disclose or change data.
The verified operator must respond and fulfil lawful requests separately.
"""
from __future__ import annotations

from datetime import datetime, timezone
import secrets

RIGHTS_KINDS = frozenset({"access", "correction", "deletion", "stop_processing"})
RIGHTS_STATUSES = frozenset({"received", "in_review", "completed", "declined"})
CLOSURE_REASONS = frozenset({"fulfilled", "retention_required", "identity_unverified", "other"})
ACTIVE_STATUSES = ("received", "in_review")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def submit_request(db, user_id: int, kind: str) -> dict:
    if kind not in RIGHTS_KINDS:
        raise ValueError("Unknown privacy request kind")
    active = db.execute(
        """SELECT request_key,kind,status,submitted_at,updated_at,closed_at
           FROM privacy_rights_requests
           WHERE user_id=? AND kind=? AND status IN ('received','in_review')
           ORDER BY submitted_at DESC LIMIT 1""",
        (user_id, kind),
    ).fetchone()
    if active is not None:
        return dict(active)
    stamp = utc_timestamp()
    key = secrets.token_urlsafe(18)
    db.execute(
        """INSERT INTO privacy_rights_requests
           (request_key,user_id,kind,status,submitted_at,updated_at)
           VALUES (?,?,?,'received',?,?) ON CONFLICT DO NOTHING""",
        (key, user_id, kind, stamp, stamp),
    )
    # A partial unique index ensures at most one active request per kind, even
    # when a user clicks twice in different tabs. Always return the saved row.
    active = db.execute(
        """SELECT request_key,kind,status,submitted_at,updated_at,closed_at
           FROM privacy_rights_requests
           WHERE user_id=? AND kind=? AND status IN ('received','in_review')
           ORDER BY submitted_at DESC LIMIT 1""",
        (user_id, kind),
    ).fetchone()
    if active is None:
        raise RuntimeError("Could not persist privacy request")
    return dict(active)


def requests_for_user(db, user_id: int) -> list[dict]:
    return [
        dict(row) for row in db.execute(
            """SELECT request_key,kind,status,submitted_at,updated_at,closed_at
               FROM privacy_rights_requests WHERE user_id=?
               ORDER BY submitted_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
    ]


def admin_request_list(db, status: str | None = None, limit: int = 100) -> list[dict]:
    if status is not None and status not in RIGHTS_STATUSES:
        raise ValueError("Unknown privacy request status")
    if not 1 <= limit <= 100:
        raise ValueError("Unsupported queue size")
    if status is None:
        sql = """SELECT r.request_key,r.kind,r.status,r.submitted_at,r.updated_at,
                        r.closed_at,r.closure_reason,u.email
                 FROM privacy_rights_requests r JOIN users u ON u.id=r.user_id
                 ORDER BY CASE WHEN r.status IN ('received','in_review') THEN 0 ELSE 1 END,
                          r.submitted_at DESC LIMIT ?"""
        args = (limit,)
    else:
        sql = """SELECT r.request_key,r.kind,r.status,r.submitted_at,r.updated_at,
                        r.closed_at,r.closure_reason,u.email
                 FROM privacy_rights_requests r JOIN users u ON u.id=r.user_id
                 WHERE r.status=? ORDER BY r.submitted_at DESC LIMIT ?"""
        args = (status, limit)
    return [dict(row) for row in db.execute(sql, args).fetchall()]


def admin_change_status(
    db,
    request_key: str,
    admin_user_id: int,
    next_status: str,
    *,
    manual_response_confirmed: bool,
    closure_reason: str | None,
) -> dict | None:
    if next_status not in {"in_review", "completed", "declined"}:
        raise ValueError("Unsupported transition")
    current = db.execute(
        """SELECT request_key,user_id,kind,status FROM privacy_rights_requests
           WHERE request_key=?""",
        (request_key,),
    ).fetchone()
    if current is None:
        return None
    initial = current["status"]
    if initial not in ACTIVE_STATUSES:
        raise ValueError("Already closed; cannot change decision silently")
    if next_status == "in_review" and initial != "received":
        raise ValueError("Only a received request can enter review")
    if next_status in {"completed", "declined"}:
        if initial != "in_review":
            raise ValueError("Review must precede final decision")
        if not manual_response_confirmed:
            raise ValueError("Confirm an actual manual response to the user")
        if closure_reason not in CLOSURE_REASONS:
            raise ValueError("Provide a categorical reason for closure")
        if next_status == "completed" and closure_reason != "fulfilled":
            raise ValueError("A completed request must be fulfilled")
        if next_status == "completed" and current["kind"] in {"deletion", "stop_processing"}:
            from .privacy_disposal import manual_completion_allowed
            if not manual_completion_allowed(db, request_key):
                raise ValueError(
                    "Deletion and processing-cessation requests require an "
                    "audited manual checklist before marking them fulfilled"
                )
        if next_status == "declined" and closure_reason == "fulfilled":
            raise ValueError("A fulfilled request must not be marked declined")
    elif closure_reason is not None:
        raise ValueError("Do not set closure reason for review")
    now = utc_timestamp()
    final = next_status in {"completed", "declined"}
    result = db.execute(
        """UPDATE privacy_rights_requests
           SET status=?,updated_at=?,closed_at=?,closure_reason=?
           WHERE request_key=? AND status=?""",
        (
            next_status, now, now if final else None,
            closure_reason if final else None, request_key, initial,
        ),
    )
    if result.rowcount != 1:
        raise ValueError("Request changed; refresh before acting")
    db.execute(
        """INSERT INTO privacy_rights_admin_actions
           (event_key,request_key,admin_user_id,from_status,to_status,changed_at)
           VALUES(?,?,?,?,?,?)""",
        (secrets.token_urlsafe(18), request_key, admin_user_id, initial, next_status, now),
    )
    return {
        "request_key": request_key, "kind": current["kind"],
        "status": next_status, "updated_at": now,
        "closed_at": now if final else None,
    }
