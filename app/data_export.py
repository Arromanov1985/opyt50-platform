"""Strictly allowlisted personal account snapshot for authenticated users.

Deliberately not a complete statutory Art.14 disclosure: other processors,
backups, recipients, retention and manual identification remain in the legal
rights-request workflow. Never dump whole tables or password/session secrets.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

MAX_SECTION_ROWS = 2000


def _list_owned(db, sql: str, owner_id: int) -> tuple[list[dict], bool]:
    """One caller-supplied owner filter, fixed SQL, bounded response."""
    rows = db.execute(sql + " LIMIT ?", (owner_id, MAX_SECTION_ROWS + 1)).fetchall()
    truncated = len(rows) > MAX_SECTION_ROWS
    return [dict(row) for row in rows[:MAX_SECTION_ROWS]], truncated


def _single(db, sql: str, owner_id: int) -> dict | None:
    row = db.execute(sql, (owner_id,)).fetchone()
    return dict(row) if row is not None else None


def _safe_json_list(raw: str | None) -> list:
    try:
        parsed = json.loads(raw or "[]")
    except (ValueError, TypeError):
        parsed = []
    return parsed if isinstance(parsed, list) else []


def build_personal_data_snapshot(db, user_id: int) -> dict:
    """User-owned fields only; no unbounded or cross-account private joins."""
    account = _single(
        db,
        "SELECT id,name,email,phone,role,created_at FROM users WHERE id=?",
        user_id,
    )
    if account is None:
        raise ValueError("Account not found")
    role = account["role"]
    data = {
        "export_format": "stazhno-self-service-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "account-owned data; not a full response under personal-data law",
        "account": account,
        "account_status": _single(
            db,
            "SELECT status,email_verified FROM account_controls WHERE user_id=?",
            user_id,
        ),
        "sections": {},
        "truncated_sections": [],
        "excluded": [
            "password hashes, login sessions, access and recovery tokens",
            "other participants' personal details and contacts",
            "internal security and administration records",
            "provider-held logs and backups; address these through the operator",
        ],
    }

    def section(name: str, sql: str) -> None:
        rows, incomplete = _list_owned(db, sql, user_id)
        data["sections"][name] = rows
        if incomplete:
            data["truncated_sections"].append(name)

    section(
        "contract_acceptances",
        """SELECT terms_version,privacy_version,accepted_at,evidence_method
           FROM legal_acceptance_records WHERE user_id=?
           ORDER BY accepted_at DESC""",
    )
    section(
        "privacy_requests",
        """SELECT kind,status,submitted_at,updated_at,closed_at,closure_reason
           FROM privacy_rights_requests WHERE user_id=?
           ORDER BY submitted_at DESC""",
    )
    if role == "candidate":
        data["candidate_profile"] = _single(
            db,
            """SELECT profession,city,skills,salary_min,schedule,employment,
                      about,is_active,updated_at
               FROM candidate_profiles WHERE user_id=?""",
            user_id,
        )
        resume = _single(
            db,
            """SELECT experience_years,education,achievements,work_history_json,updated_at
               FROM candidate_resume_details WHERE user_id=?""",
            user_id,
        )
        if resume:
            resume["work_history"] = _safe_json_list(resume.pop("work_history_json"))
        data["resume"] = resume
        qualifications = _single(
            db,
            """SELECT specializations,courses_json,updated_at
               FROM candidate_resume_qualifications WHERE user_id=?""",
            user_id,
        )
        if qualifications:
            qualifications["courses"] = _safe_json_list(qualifications.pop("courses_json"))
        data["additional_qualifications"] = qualifications
        section(
            "my_applications",
            """SELECT id,vacancy_id,status,created_at,updated_at
               FROM job_applications WHERE candidate_id=?
               ORDER BY created_at DESC,id DESC""",
        )
        section(
            "application_status_history",
            """SELECT ev.application_id,ev.event,ev.created_at
               FROM application_events ev
               JOIN job_applications a ON a.id=ev.application_id
               WHERE a.candidate_id=?
               ORDER BY ev.id DESC""",
        )
        section(
            "my_favorites",
            """SELECT vacancy_id,created_at
               FROM candidate_favorites WHERE candidate_id=?
               ORDER BY created_at DESC""",
        )
        section(
            "my_invitations",
            """SELECT id,vacancy_id,status,share_consent,contact_shared,
                      created_at,responded_at
               FROM invitations WHERE candidate_id=?
               ORDER BY created_at DESC,id DESC""",
        )
    elif role == "employer":
        data["company_profile"] = _single(
            db,
            "SELECT company_name,inn,verified FROM employer_profiles WHERE user_id=?",
            user_id,
        )
        data["public_company_description"] = _single(
            db,
            "SELECT about,updated_at FROM employer_public_profiles WHERE employer_id=?",
            user_id,
        )
        section(
            "my_vacancies",
            """SELECT id,title,city,salary_min,salary_max,schedule,employment,
                      skills,description,status,created_at
               FROM vacancies WHERE employer_id=?
               ORDER BY created_at DESC,id DESC""",
        )
        section(
            "my_vacancy_drafts",
            """SELECT id,fields_json,version,published_vacancy_id,updated_at
               FROM vacancy_drafts WHERE employer_id=?
               ORDER BY updated_at DESC,id DESC""",
        )
        # Do not export candidate IDs, contact details or applicant profiles.
        section(
            "my_invitation_actions",
            """SELECT id,vacancy_id,status,share_consent,contact_shared,
                      created_at,responded_at
               FROM invitations WHERE employer_id=?
               ORDER BY created_at DESC,id DESC""",
        )

    data["has_incomplete_sections"] = bool(data["truncated_sections"])
    return data
