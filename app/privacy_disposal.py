"""Privacy deletion/cessation preflight: read-only impact + manual review evidence.

NO function in this module deletes, anonymizes, exports, emails, or disables an
account. A completed checklist is a human attestation, NOT proof of erasure.
Only fixed, owner-filtered SQL and aggregate counts leave the administrative API.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
)
CANDIDATE_COUNTS = (
    ("professional_profile", "SELECT COUNT(*) FROM candidate_profiles WHERE user_id=?", "id"),
    ("resume", "SELECT COUNT(*) FROM candidate_resume_details WHERE user_id=?", "id"),
    ("qualifications", "SELECT COUNT(*) FROM candidate_resume_qualifications WHERE user_id=?", "id"),
    ("applications", "SELECT COUNT(*) FROM job_applications WHERE candidate_id=?", "id"),
    ("application_events", """SELECT COUNT(*) FROM application_events ev
        JOIN job_applications a ON a.id=ev.application_id WHERE a.candidate_id=?""", "id"),
    ("favorite_vacancies", "SELECT COUNT(*) FROM candidate_favorites WHERE candidate_id=?", "id"),
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
    if counts.get("contacts_already_shared", 0):
        risks.append("Контакты ранее раскрывались: оценить уведомление конкретных получателей")
    if counts.get("candidate_applications_affected", 0):
        risks.append("Вакансии содержат отклики третьих лиц: удалить их вместе с работодателем нельзя без оценки")
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
                  reviewed_at
           FROM privacy_disposal_reviews WHERE request_key=?""",
        (request_key,),
    ).fetchone()
    fields = {
        k: bool(row[k]) if row is not None else False for k in CHECKS
    }
    return {
        "request_key": request_key,
        "kind": request["kind"],
        "status": request["status"],
        "checks": fields,
        "labels": REVIEW_LABELS,
        "ready_for_manual_closure": all(fields.values()),
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
    columns = ",".join(CHECKS)
    values = [int(checks[key]) for key in CHECKS]
    placeholders = ",".join("?" for _ in CHECKS)
    updates = ",".join(f"{key}=excluded.{key}" for key in CHECKS)
    db.execute(
        f"""INSERT INTO privacy_disposal_reviews
            (request_key,{columns},reviewed_at,reviewed_by)
            VALUES(?,{placeholders},?,?)
            ON CONFLICT(request_key) DO UPDATE SET
            {updates},reviewed_at=excluded.reviewed_at,
            reviewed_by=excluded.reviewed_by""",
        (request_key, *values, now, admin_id),
    )
    db.execute(
        """INSERT INTO privacy_disposal_review_actions
           (event_key,request_key,reviewed_by,reviewed_at,checks_bits)
           VALUES(?,?,?,?,?)""",
        (
            secrets.token_urlsafe(16), request_key, admin_id, now,
            "".join("1" if checks[key] else "0" for key in CHECKS),
        ),
    )
    return review_state(db, request_key)


def manual_completion_allowed(db, request_key: str) -> bool:
    review = review_state(db, request_key)
    return bool(review and review["ready_for_manual_closure"])
