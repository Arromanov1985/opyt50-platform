"""Independent product totals from existing records, without personal tracking.

Profile completeness is a current snapshot: no first-completed timestamp exists.
Dated totals describe retained records in a UTC period, never an attributed funnel.
Contact opening is currently a demo operation; outcomes are employer statements,
not evidence of an interview or employment.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def product_snapshot(db: Any, since: str, through: str) -> dict:
    """Return counts only, separating current availability from dated actions.

    Dates are inclusive calendar days. The exclusive next-day boundary works
    with both supported databases and the existing UTC text timestamp formats.
    Current profile checks mirror candidateProfileHealth's five saved fields.
    """
    first, last = date.fromisoformat(since), date.fromisoformat(through)
    if first > last:
        raise ValueError("Invalid product reporting period")
    bounds = (first.isoformat(), (last + timedelta(days=1)).isoformat())

    def count(sql: str, params: tuple = ()) -> int:
        return int(db.execute(sql, params).fetchone()[0])

    current = {
        "enabled_candidate_accounts": count(
            """SELECT COUNT(*) FROM users u
               LEFT JOIN account_controls c ON c.user_id=u.id
               WHERE u.role='candidate' AND COALESCE(c.status,'active')='active'"""
        ),
        "completed_active_candidate_profiles": count(
            """SELECT COUNT(*) FROM candidate_profiles p
               JOIN users u ON u.id=p.user_id AND u.role='candidate'
               LEFT JOIN account_controls c ON c.user_id=u.id
               WHERE p.is_active=1 AND COALESCE(c.status,'active')='active'
                 AND trim(p.profession)<>'' AND trim(p.city)<>''
                 AND p.salary_min>0 AND trim(p.skills)<>'' AND trim(p.about)<>''"""
        ),
    }
    period = {
        # Creation is timestamped; first publication/moderation approval is not.
        "vacancies_created": count(
            """SELECT COUNT(*) FROM vacancies
               WHERE substr(created_at,1,10)>=? AND substr(created_at,1,10)<?""",
            bounds,
        ),
        # A reapplication updates the same unique vacancy/candidate pair.
        "new_applications": count(
            """SELECT COUNT(*) FROM job_applications
               WHERE substr(created_at,1,10)>=? AND substr(created_at,1,10)<?""",
            bounds,
        ),
        "consented_introductions": count(
            """SELECT COUNT(*) FROM invitations
               WHERE status='accepted' AND share_consent=1
                 AND substr(responded_at,1,10)>=? AND substr(responded_at,1,10)<?""",
            bounds,
        ),
        # The unique demo transaction timestamps the first contact opening.
        "demo_contacts_opened": count(
            """SELECT COUNT(*) FROM demo_transactions d
               JOIN invitations i ON i.id=d.invitation_id
               WHERE i.status='accepted' AND i.share_consent=1 AND i.contact_shared=1
                 AND substr(d.created_at,1,10)>=? AND substr(d.created_at,1,10)<?""",
            bounds,
        ),
    }
    # A direct result can predate a later application for the same pair. Give
    # that immutable result precedence to count each introduction only once.
    # Application outcomes require an actual terminal history event after
    # contact opening; an old rejection before an invitation is not its result.
    outcomes = db.execute(
        """SELECT outcome,COUNT(*) AS total FROM (
             SELECT i.id,io.outcome,
                    replace(substr(io.recorded_at,1,19),'T',' ') AS occurred_at
             FROM invitations i
             JOIN demo_transactions d ON d.invitation_id=i.id
             JOIN invitation_outcomes io ON io.invitation_id=i.id
             WHERE i.status='accepted' AND i.share_consent=1 AND i.contact_shared=1
               AND replace(substr(io.recorded_at,1,19),'T',' ')
                   >=replace(substr(d.created_at,1,19),'T',' ')
             UNION ALL
             SELECT i.id,a.status AS outcome,
                    MIN(replace(substr(e.created_at,1,19),'T',' ')) AS occurred_at
             FROM invitations i
             JOIN demo_transactions d ON d.invitation_id=i.id
             JOIN job_applications a
                  ON a.vacancy_id=i.vacancy_id AND a.candidate_id=i.candidate_id
             JOIN application_events e ON e.application_id=a.id AND e.event=a.status
             WHERE i.status='accepted' AND i.share_consent=1 AND i.contact_shared=1
               AND a.status IN ('hired','rejected')
               AND NOT EXISTS (SELECT 1 FROM invitation_outcomes io WHERE io.invitation_id=i.id)
               AND replace(substr(e.created_at,1,19),'T',' ')
                   >=replace(substr(d.created_at,1,19),'T',' ')
             GROUP BY i.id,a.status
           ) AS results
           WHERE substr(occurred_at,1,10)>=? AND substr(occurred_at,1,10)<?
           GROUP BY outcome""",
        bounds,
    ).fetchall()
    outcome_counts = {row["outcome"]: int(row["total"]) for row in outcomes}
    period["positive_outcomes"] = outcome_counts.get("hired", 0)
    period["no_agreement_outcomes"] = outcome_counts.get("rejected", 0)
    period["introductions_completed"] = sum(outcome_counts.values())
    return {
        "current": current,
        "period": period,
        "limitations": [
            "Профили показаны на текущий момент: дата первого заполнения не сохраняется. "
            "Полный активный профиль содержит профессию, город, зарплатные ожидания, навыки и описание опыта.",
            "Показатели за период независимы друг от друга и от журнала. "
            "Новые вакансии считаются по созданию, не по публикации; повторный отклик не создаёт новую заявку.",
            "Контакты открываются в демонстрационном режиме. Итоги отмечены работодателями "
            "и не подтверждают собеседование или трудоустройство.",
            "Считаются сохранившиеся записи этой базы, включая тестовые; "
            "удаление аккаунтов и связанных данных может изменить исторические итоги.",
        ],
    }
