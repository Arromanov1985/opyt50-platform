"""Conservative, non-destructive interim restriction after a privacy request.

This stops *new* marketplace activity in the app while the operator reviews a
deletion or processing-cessation request. It does not delete data, invalidate
existing legal bases, revoke past third-party disclosures, or block a subject's
ability to view/export their own data and contact the operator.
"""
from __future__ import annotations

RESTRICTED_KINDS = ("deletion", "stop_processing")
RESTRICTED_STATUSES = ("received", "in_review", "completed")
BUSINESS_PREFIXES = ("/api/candidate/", "/api/employer/")
MATCHING_READS = (
    "/api/candidate/jobs",
    "/api/candidate/alternative-jobs",
)


def restriction_is_active(db, user_id: int) -> bool:
    return db.execute(
        """SELECT 1 FROM privacy_rights_requests
           WHERE user_id=? AND kind IN ('deletion','stop_processing')
             AND status IN ('received','in_review','completed')
           LIMIT 1""",
        (user_id,),
    ).fetchone() is not None


def marketplace_action_restricted(db, user_id: int, method: str, path: str) -> bool:
    """Guard business routes, preserving read-only account and rights access.

    No blanket ban on /api/account/: password/session security, personal data
    export and privacy requests remain available. Ordinary history and profile
    GET requests remain available; automated matching GET requests do not.
    """
    if method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/community/"):
        # Keep access to history and safe shutdown/reporting actions; prevent
        # creating or extending a public professional identity or conversation.
        safety_action = (
            (method == "DELETE" and path == "/api/community/profile/publication")
            or (method == "POST" and path == "/api/community/reports")
            or (method == "POST" and path.startswith("/api/community/connections/")
                and path.rsplit("/", 1)[-1] in {"cancel", "block"})
        )
        return not safety_action and restriction_is_active(db, user_id)
    if method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith(BUSINESS_PREFIXES):
        return restriction_is_active(db, user_id)
    if method == "GET" and (
        path in MATCHING_READS
        or (path.startswith("/api/employer/vacancies/") and path.endswith("/matches"))
    ):
        return restriction_is_active(db, user_id)
    return False
