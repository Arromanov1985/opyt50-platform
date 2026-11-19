"""Regression tests for private, strictly allowlisted self-service JSON exports.

Uses fictional accounts and an isolated DB. Exports are subsets, not complete
legal access responses or server-side backup archives.
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.data_export import build_personal_data_snapshot
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}
PASSWORD = "Unique test account password 2026"


def register(client, role, email):
    body = {
        "role": role,
        "name": "Тестовый участник",
        "email": email,
        "password": PASSWORD,
    }
    if role == "employer":
        body["company_name"] = "Пример компании"
    response = client.post("/api/register", headers=XHR, json=body)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def test_private_export_needs_session_and_never_returns_other_people(tmp_path: Path):
    app = create_app(str(tmp_path / "export.db"))
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as visitor:
        candidate_id = register(candidate, "candidate", "owner@example.invalid")
        employer_id = register(employer, "employer", "unrelated-employer@example.invalid")
        assert visitor.get("/api/account/data-export").status_code == 401
        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE candidate_profiles SET profession=?,city=? WHERE user_id=?",
                ("Инженер по оборудованию", "Москва", candidate_id),
            )
            vacancy = db.execute(
                """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,skills)
                   VALUES(?,?,?,?,?,?)""",
                (employer_id, "Инженер", "Москва", 60000, 90000, "Работа"),
            ).lastrowid
            db.execute(
                "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)",
                (vacancy, candidate_id),
            )
            db.execute(
                """INSERT INTO invitations(vacancy_id,candidate_id,employer_id,price_rub)
                   VALUES(?,?,?,?)""",
                (vacancy, candidate_id, employer_id, 0),
            )
            db.execute(
                """INSERT INTO candidate_resume_details(user_id,experience_years,education,achievements,work_history_json)
                   VALUES(?,?,?,?,?)""",
                (candidate_id, 17, "Техникум", "Наладил процессы",
                 json.dumps([{"position":"Инженер","period":"2010-2025"}], ensure_ascii=False)),
            )
            db.execute(
                """INSERT INTO legal_acceptance_records
                   (user_id,terms_version,privacy_version,accepted_at,evidence_method)
                   VALUES(?,?,?,?,?)""",
                (candidate_id, "test-terms", "test-privacy", "2026-11-19T00:00:00+00:00",
                 "explicit-checkbox"),
            )
            db.execute(
                """INSERT INTO privacy_rights_requests
                   (request_key,user_id,kind,status,submitted_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                ("owner-request-000001", candidate_id, "access", "received",
                 "2026-11-19T00:00:00+00:00", "2026-11-19T00:00:00+00:00"),
            )
        response = candidate.get("/api/account/data-export")
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert "attachment" in response.headers["content-disposition"]
        assert response.headers["content-type"].startswith("application/json")
        exported = response.json()
        assert exported["export_format"] == "stazhno-self-service-v1"
        assert exported["account"]["id"] == candidate_id
        assert exported["account"]["email"] == "owner@example.invalid"
        assert exported["candidate_profile"]["profession"] == "Инженер по оборудованию"
        assert exported["resume"]["experience_years"] == 17
        assert exported["resume"]["work_history"][0]["position"] == "Инженер"
        assert len(exported["sections"]["my_applications"]) == 1
        assert len(exported["sections"]["my_invitations"]) == 1
        assert len(exported["sections"]["contract_acceptances"]) == 1
        assert len(exported["sections"]["privacy_requests"]) == 1
        assert "company_profile" not in exported
        dumped = json.dumps(exported, ensure_ascii=False)
        assert "unrelated-employer@example.invalid" not in dumped
        assert "password_hash" not in dumped
        assert PASSWORD not in dumped
        assert "token_hash" not in dumped
        assert "sessions" not in exported
        assert "users" not in exported
        assert "contact_shared" in exported["sections"]["my_invitations"][0]


def test_employer_export_excludes_candidate_private_data(tmp_path: Path):
    app = create_app(str(tmp_path / "export-employer.db"))
    with TestClient(app) as employer, TestClient(app) as candidate:
        eid = register(employer, "employer", "company@example.invalid")
        cid = register(candidate, "candidate", "candidate-secret@example.invalid")
        with database(app.state.db_path) as db:
            vacancy = db.execute(
                """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,skills)
                   VALUES(?,?,?,?,?,?)""",
                (eid, "Менеджер по продажам", "Подольск", 70000, 100000, "B2B"),
            ).lastrowid
            db.execute(
                """INSERT INTO invitations(vacancy_id,candidate_id,employer_id,price_rub)
                   VALUES(?,?,?,?)""",
                (vacancy, cid, eid, 1490),
            )
            db.execute(
                "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)",
                (vacancy, cid),
            )
            db.execute(
                "INSERT INTO vacancy_drafts(employer_id,fields_json) VALUES(?,?)",
                (eid, '{"title":"Планируемая вакансия"}'),
            )
        res = employer.get("/api/account/data-export")
        assert res.status_code == 200
        data = res.json()
        assert data["account"]["id"] == eid
        assert data["company_profile"]["company_name"] == "Пример компании"
        assert data["sections"]["my_vacancies"][0]["title"] == "Менеджер по продажам"
        assert data["sections"]["my_invitation_actions"][0]["vacancy_id"] == vacancy
        assert "candidate_id" not in data["sections"]["my_invitation_actions"][0]
        assert "my_applications" not in data["sections"]
        dumped = json.dumps(data, ensure_ascii=False)
        assert "candidate-secret@example.invalid" not in dumped
        assert "password_hash" not in dumped
        assert "session" not in data
        assert "about" not in data["company_profile"]  # public description is separate


def test_export_limits_each_section_and_discloses_truncation(tmp_path, monkeypatch):
    import app.data_export as module

    app = create_app(str(tmp_path / "export-bounded.db"))
    with TestClient(app) as client:
        uid = register(client, "candidate", "bounded@example.invalid")
        with database(app.state.db_path) as db:
            for i in range(7):
                db.execute(
                    """INSERT INTO privacy_rights_requests
                       (request_key,user_id,kind,status,submitted_at,updated_at,closed_at,closure_reason)
                       VALUES(?,?,?,'completed',?,?,?,'fulfilled')""",
                    (f"key-for-closure-{i:05d}", uid, "access",
                     f"2026-11-19T00:00:{i:02d}+00:00", f"2026-11-19T00:00:{i:02d}+00:00",
                     f"2026-11-19T00:00:{i:02d}+00:00"),
                )
            monkeypatch.setattr(module, "MAX_SECTION_ROWS", 3)
            snapshot = build_personal_data_snapshot(db, uid)
        assert len(snapshot["sections"]["privacy_requests"]) == 3
        assert snapshot["truncated_sections"] == ["privacy_requests"]
        assert snapshot["has_incomplete_sections"] is True
