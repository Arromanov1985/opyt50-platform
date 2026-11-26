"""Privacy deletion/cessation preflight: read-only impact + manual review evidence.

NO function in this module deletes, anonymizes, exports, emails, or disables an
account. A completed checklist is a human attestation, NOT proof of erasure.
Only fixed, owner-filtered SQL and aggregate counts leave the administrative API.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets

DISPOSITION_KINDS = frozenset(("deletion", "stop_processing"))
CHECKS = (
    "identity_reviewed",
    "lawful_basis_reviewed",
    "retention_reviewed",
    "linked_data_reviewed",
    "recipients_reviewed",
    "backups_and_processors_reviewed",
    "manual_action_verified",
)
REVIEW_LABELS = {
    "identity_reviewed": "Личность и полномочия заявителя проверены",
    "lawful_basis_reviewed": "Проверены цели и правовые основания",
    "retention_reviewed": "Определено, какие записи необходимо сохранить по закону",
    "linked_data_reviewed": "Проверены связанные вакансии, отклики и чужие права",
    "recipients_reviewed": "Оценены ранее раскрытые контакты и адресаты",
    "backups_and_processors_reviewed": "Проверены резервные копии, почта и внешние обработчики",
    "manual_action_verified": "Фактически выполнены разрешённые действия вне этого интерфейса",
}
COMMON_COUNTS = (
    ("active_sessions", "SELECT COUNT(*) FROM sessions WHERE user_id=?", "id"),
    ("auth_tokens", "SELECT COUNT(*) FROM email_tokens WHERE user_id=?", "id"),
    ("saved_devices", "SELECT COUNT(*) FROM account_devices WHERE user_id=?", "id"),
    ("legal_acceptances", "SELECT COUNT(*) FROM legal_acceptance_records WHERE user_id=?", "id"),
    ("rights_requests", "SELECT COUNT(*) FROM privacy_rights_requests WHERE user_id=?", "id"),
    ("security_events", "SELECT COUNT(*) FROM security_events WHERE user_id=?", "id"),
    ("service_emails", "SELECT COUNT(*) FROM email_outbox WHERE to_email=?", "email"),
    ("delivery_links", "SELECT COUNT(*) FROM email_delivery_recipients WHERE user_id=?", "id"),
    ("community_read_state", "SELECT COUNT(*) FROM community_read_state WHERE user_id=?", "id"),
    ("community_connections", "SELECT COUNT(*) FROM community_connections WHERE ? IN (sender_id,recipient_id)", "id"),
    ("community_messages_authored", "SELECT COUNT(*) FROM community_messages WHERE sender_id=?", "id"),
    ("community_reports_submitted", "SELECT COUNT(*) FROM community_reports WHERE reporter_id=?", "id"),
    ("community_opportunities", """SELECT COUNT(*) FROM community_opportunities o
        JOIN community_feed_entries f ON f.id=o.entry_id WHERE f.author_id=?""", "id"),
    ("community_group_memberships", "SELECT COUNT(*) FROM community_group_memberships WHERE user_id=?", "id"),
    ("community_group_posts", """SELECT COUNT(*) FROM community_group_posts g
        JOIN community_feed_entries f ON f.id=g.entry_id WHERE f.author_id=?""", "id"),
    ("community_feed_entries", "SELECT COUNT(*) FROM community_feed_entries WHERE author_id=?", "id"),
    ("community_feed_linked_comments", """SELECT COUNT(*) FROM community_feed_entries reply
        JOIN community_feed_entries root ON root.id=reply.parent_id
        WHERE root.author_id=? AND reply.author_id<>root.author_id""", "id"),
    ("community_saved_entries", "SELECT COUNT(*) FROM community_saved_entries WHERE user_id=?", "id"),
    ("community_discovery_preferences", "SELECT COUNT(*) FROM community_discovery_preferences WHERE user_id=?", "id"),
    ("community_saved_entries_affected", """SELECT COUNT(*) FROM community_saved_entries s
        JOIN community_feed_entries f ON f.id=s.entry_id WHERE f.author_id=? AND f.author_id<>s.user_id""", "id"),
    ("community_feed_follows", "SELECT COUNT(*) FROM community_feed_follows WHERE follower_id=?", "id"),
    ("community_feed_followers_affected", "SELECT COUNT(*) FROM community_feed_follows WHERE target_id=?", "id"),
    ("community_feed_alert_reads", "SELECT COUNT(*) FROM community_feed_alert_reads WHERE user_id=?", "id"),
    ("community_feed_reports_submitted", "SELECT COUNT(*) FROM community_feed_reports WHERE reporter_id=?", "id"),
    ("community_feed_linked_alert_reads", """SELECT COUNT(*) FROM community_feed_alert_reads a
        JOIN community_feed_entries f ON f.id=a.entry_id
        LEFT JOIN community_feed_entries root ON root.id=f.parent_id
        WHERE ? IN (f.author_id,root.author_id)""", "id"),
    ("community_feed_linked_reports", """SELECT COUNT(*) FROM community_feed_reports r
        JOIN community_feed_entries f ON f.id=r.entry_id
        LEFT JOIN community_feed_entries root ON root.id=f.parent_id
        WHERE ? IN (f.author_id,root.author_id)""", "id"),
    ("community_recommendations", "SELECT COUNT(*) FROM community_recommendations WHERE ? IN (author_id,recipient_id)", "id"),
    ("community_portfolio_entries", "SELECT COUNT(*) FROM community_portfolio_entries WHERE user_id=?", "id"),
    ("community_professional_profile", "SELECT COUNT(*) FROM community_profiles WHERE user_id=?", "id"),
    ("workflow_mail_awaiting", """SELECT COUNT(*) FROM email_delivery_jobs q
        JOIN email_delivery_recipients r ON r.outbox_id=q.outbox_id
        WHERE r.user_id=? AND q.state IN ('pending','leased')""", "id"),
    ("workflow_mail_privacy_suppressed", """SELECT COUNT(*) FROM email_delivery_jobs q
        JOIN email_delivery_recipients r ON r.outbox_id=q.outbox_id
        WHERE r.user_id=? AND q.last_error_code='privacy_request'""", "id"),
)
CANDIDATE_COUNTS = (
    ("professional_profile", "SELECT COUNT(*) FROM candidate_profiles WHERE user_id=?", "id"),
    ("resume", "SELECT COUNT(*) FROM candidate_resume_details WHERE user_id=?", "id"),
    ("qualifications", "SELECT COUNT(*) FROM candidate_resume_qualifications WHERE user_id=?", "id"),
    ("applications", "SELECT COUNT(*) FROM job_applications WHERE candidate_id=?", "id"),
    ("application_events", """SELECT COUNT(*) FROM application_events ev
        JOIN job_applications a ON a.id=ev.application_id WHERE a.candidate_id=?""", "id"),
    ("favorite_vacancies", "SELECT COUNT(*) FROM candidate_favorites WHERE candidate_id=?", "id"),
    ("saved_searches", "SELECT COUNT(*) FROM candidate_saved_searches WHERE candidate_id=?", "id"),
    ("invitations", "SELECT COUNT(*) FROM invitations WHERE candidate_id=?", "id"),
    ("contacts_already_shared", """SELECT COUNT(*) FROM invitations
        WHERE candidate_id=? AND contact_shared=1""", "id"),
    ("vacancy_update_receipts", "SELECT COUNT(*) FROM vacancy_update_recipients WHERE candidate_id=?", "id"),
    ("reports_submitted", "SELECT COUNT(*) FROM content_reports WHERE reporter_id=?", "id"),
)
EMPLOYER_COUNTS = (
    ("company_profile", "SELECT COUNT(*) FROM employer_profiles WHERE user_id=?", "id"),
    ("public_company_profile", "SELECT COUNT(*) FROM employer_public_profiles WHERE employer_id=?", "id"),
    ("published_vacancies", "SELECT COUNT(*) FROM vacancies WHERE employer_id=?", "id"),
    ("open_vacancies", "SELECT COUNT(*) FROM vacancies WHERE employer_id=? AND status='open'", "id"),
    ("vacancy_drafts", "SELECT COUNT(*) FROM vacancy_drafts WHERE employer_id=?", "id"),
    ("candidate_applications_affected", """SELECT COUNT(*) FROM job_applications a
        JOIN vacancies v ON v.id=a.vacancy_id WHERE v.employer_id=?""", "id"),
    ("invitations", "SELECT COUNT(*) FROM invitations WHERE employer_id=?", "id"),
    ("contacts_already_shared", """SELECT COUNT(*) FROM invitations
        WHERE employer_id=? AND contact_shared=1""", "id"),
    ("vacancy_updates", "SELECT COUNT(*) FROM vacancy_updates WHERE employer_id=?", "id"),
    ("reports_about_employer", "SELECT COUNT(*) FROM content_reports WHERE employer_id=?", "id"),
)


def _request(db, key: str):
    return db.execute(
        """SELECT r.request_key,r.kind,r.status,r.user_id,u.role,u.email
           FROM privacy_rights_requests r JOIN users u ON u.id=r.user_id
           WHERE r.request_key=?""", (key,),
    ).fetchone()


def impact_preview(db, request_key: str) -> dict | None:
    row = _request(db, request_key)
    if row is None:
        return None
    if row["kind"] not in DISPOSITION_KINDS:
        raise ValueError("Impact preview applies only to deletion or processing cessation")
    records = COMMON_COUNTS + (
        CANDIDATE_COUNTS if row["role"] == "candidate" else EMPLOYER_COUNTS
    )
    values = {"id": int(row["user_id"]), "email": row["email"]}
    counts = {
        label: int(db.execute(sql, (values[which],)).fetchone()[0])
        for label, sql, which in records
    }
    risks = ["Проверить правовые основания и сроки хранения по каждому виду данных",
             "Проверить почтовые очереди, системные журналы и резервные копии",
             "Не удалять автоматически аккаунт, заявки и доказательства согласий"]
    if counts.get("workflow_mail_awaiting", 0):
        risks.append("В очереди остаются рабочие уведомления; проверьте подавление до закрытия обращения")
    if counts.get("contacts_already_shared", 0):
        risks.append("Контакты ранее раскрывались: оценить уведомление конкретных получателей")
    if counts.get("candidate_applications_affected", 0):
        risks.append("Вакансии содержат отклики третьих лиц: удалить их вместе с работодателем нельзя без оценки")
    if any(counts.get(key, 0) for key in ("community_feed_followers_affected", "community_feed_linked_alert_reads", "community_feed_linked_reports", "community_saved_entries_affected")):
        risks.append("Проверить связанные подписки, сохранённые записи, отметки уведомлений и жалобы других участников")
    if counts.get("community_recommendations", 0):
        risks.append("Рекомендации затрагивают согласия и данные двух участников: отдельно оценить права второй стороны")
    if counts.get("community_feed_linked_comments", 0):
        risks.append("Удаление публикаций затронет комментарии других участников: отдельно оцените их права и сохранность")
    if counts.get("applications", 0):
        risks.append("Отклики кандидата связаны с процессами работодателей")
    return {
        "request_key": request_key,
        "kind": row["kind"],
        "status": row["status"],
        "account_role": row["role"],
        "counts": counts,
        "risk_flags": risks,
        "external_systems_not_scanned": [
            "Timeweb infrastructure logs", "SMTP queues and provider logs",
            "database backups", "third-party recipients' copies",
        ],
        "read_only": True,
        "automatic_deletion": False,
        "data_is_current_estimate": True,
    }


def _impact_digest(preview: dict) -> str:
    """No personal data: fingerprint of aggregate section counts and role."""
    payload = {
        "kind": preview["kind"],
        "role": preview["account_role"],
        "counts": preview["counts"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def review_state(db, request_key: str) -> dict | None:
    request = _request(db, request_key)
    if request is None:
        return None
    if request["kind"] not in DISPOSITION_KINDS:
        raise ValueError("Review applies only to deletion or processing cessation")
    row = db.execute(
        """SELECT identity_reviewed,lawful_basis_reviewed,retention_reviewed,
                  linked_data_reviewed,recipients_reviewed,
                  backups_and_processors_reviewed,manual_action_verified,
                  impact_digest,reviewed_at
           FROM privacy_disposal_reviews WHERE request_key=?""",
        (request_key,),
    ).fetchone()
    fields = {
        k: bool(row[k]) if row is not None else False for k in CHECKS
    }
    current = impact_preview(db, request_key)
    changed = row is not None and row["impact_digest"] != _impact_digest(current)
    from .privacy_external import external_review_status
    external = external_review_status(db, request_key)
    external_ready = bool(external and external["ready_for_manual_closure"])
    return {
        "request_key": request_key,
        "kind": request["kind"],
        "status": request["status"],
        "checks": fields,
        "labels": REVIEW_LABELS,
        "counts_changed_since_review": bool(changed),
        "external_checks_ready": external_ready,
        "ready_for_manual_closure": all(fields.values()) and not changed and external_ready,
        "reviewed_at": row["reviewed_at"] if row is not None else None,
        "actual_deletion_performed_by_system": False,
    }


def update_review(db, request_key: str, admin_id: int, checks: dict) -> dict | None:
    request = _request(db, request_key)
    if request is None:
        return None
    if request["kind"] not in DISPOSITION_KINDS:
        raise ValueError("Only deletion or processing cessation needs a disposal review")
    if request["status"] != "in_review":
        raise ValueError("Start manual review before changing the checklist")
    if set(checks) != set(CHECKS) or any(type(value) is not bool for value in checks.values()):
        raise ValueError("All checklist flags must be explicit booleans")
    now = datetime.now(timezone.utc).isoformat()
    values = [int(checks[key]) for key in CHECKS]
    digest = _impact_digest(impact_preview(db, request_key))
    db.execute(
        """INSERT INTO privacy_disposal_reviews
           (request_key,identity_reviewed,lawful_basis_reviewed,retention_reviewed,
            linked_data_reviewed,recipients_reviewed,backups_and_processors_reviewed,
            manual_action_verified,reviewed_at,reviewed_by,impact_digest)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(request_key) DO UPDATE SET
            identity_reviewed=excluded.identity_reviewed,
            lawful_basis_reviewed=excluded.lawful_basis_reviewed,
            retention_reviewed=excluded.retention_reviewed,
            linked_data_reviewed=excluded.linked_data_reviewed,
            recipients_reviewed=excluded.recipients_reviewed,
            backups_and_processors_reviewed=excluded.backups_and_processors_reviewed,
            manual_action_verified=excluded.manual_action_verified,
            reviewed_at=excluded.reviewed_at,
            reviewed_by=excluded.reviewed_by,
            impact_digest=excluded.impact_digest""",
        (request_key, *values, now, admin_id, digest),
    )
    db.execute(
        """INSERT INTO privacy_disposal_review_actions
           (event_key,request_key,reviewed_by,reviewed_at,checks_bits,impact_digest)
           VALUES(?,?,?,?,?,?)""",
        (
            secrets.token_urlsafe(16), request_key, admin_id, now,
            "".join("1" if checks[key] else "0" for key in CHECKS), digest,
        ),
    )
    return review_state(db, request_key)


def manual_completion_allowed(db, request_key: str) -> bool:
    review = review_state(db, request_key)
    return bool(review and review["ready_for_manual_closure"])
