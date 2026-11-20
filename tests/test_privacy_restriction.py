"""Interim privacy restriction: stop new matchmaking, never destroy data.

All accounts and records here are fictional and created in an isolated test DB.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.privacy_restriction import restriction_is_active

XHR = {"X-Requested-With": "OPYT50"}


def register(client: TestClient, role: str, email: str) -> int:
    payload = {
        "email": email, "name": "Тестовый участник",
        "password": "StrongSyntheticPassword2026!",
        "role": role,
    }
    if role == "employer":
        payload["company_name"] = "Тестовая компания"
    result = client.post("/api/register", headers=XHR, json=payload)
    assert result.status_code == 201, result.text
    return int(result.json()["user"]["id"])


def create_vacancy_and_resume(app, employer_id, candidate_id):
    with database(app.state.db_path) as db:
        db.execute(
            """UPDATE candidate_profiles SET
               profession='Кладовщик',city='Москва',skills='Склад',
               salary_min=50000,is_active=1 WHERE user_id=?""",
            (candidate_id,),
        )
        vacancy_id = db.execute(
            """INSERT INTO vacancies
               (employer_id,title,city,salary_min,salary_max,skills)
               VALUES(?,?,?,?,?,?)""",
            (employer_id, "Кладовщик", "Москва", 50000, 90000, "Склад"),
        ).lastrowid
    return vacancy_id


def request_restriction(client, kind: str) -> str:
    response = client.post(
        "/api/account/privacy-requests", headers=XHR, json={"kind": kind}
    )
    assert response.status_code == 201, response.text
    return response.json()["request"]["request_key"]


def test_candidate_request_blocks_new_activity_but_preserves_access(tmp_path: Path):
    app = create_app(str(tmp_path / "candidate-restricted.db"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        candidate_id = register(candidate, "candidate", "candidate@example.invalid")
        employer_id = register(employer, "employer", "employer@example.invalid")
        vacancy_id = create_vacancy_and_resume(app, employer_id, candidate_id)

        with database(app.state.db_path) as db:
            assert not restriction_is_active(db, candidate_id)
        key = request_restriction(candidate, "stop_processing")
        assert key
        assert candidate.get("/api/me").status_code == 200
        assert candidate.get("/api/account/privacy-requests").status_code == 200
        export = candidate.get("/api/account/data-export")
        assert export.status_code == 200
        assert "no-store" in export.headers.get("cache-control", "")
        assert candidate.get("/api/candidate/jobs").status_code == 409
        assert candidate.get("/api/candidate/alternative-jobs").status_code == 409
        assert candidate.put("/api/candidate/profile", headers=XHR, json={
            "profession": "Кладовщик", "city": "Москва",
            "salary_min": 50000,
        }).status_code == 409
        assert candidate.post(
            "/api/candidate/applications", headers=XHR,
            json={"vacancy_id": vacancy_id},
        ).status_code == 409

        # A different active employer cannot initiate a new introduction.
        invite = employer.post(
            "/api/employer/invitations", headers=XHR,
            json={"vacancy_id": vacancy_id, "candidate_id": candidate_id},
        )
        assert invite.status_code == 422, invite.text
        matches = employer.get(f"/api/employer/vacancies/{vacancy_id}/matches")
        assert matches.status_code == 200, matches.text
        assert all(
            item["candidate_id"] != candidate_id
            for item in matches.json()["matches"]
        )
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM users WHERE id=?", (candidate_id,)).fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0
            db.execute(
                "UPDATE privacy_rights_requests SET status='declined' WHERE request_key=?",
                (key,),
            )
        assert candidate.get("/api/candidate/jobs").status_code == 200


def test_employer_request_hides_public_pages_and_blocks_new_activity(tmp_path: Path):
    app = create_app(str(tmp_path / "employer-restricted.db"))
    with TestClient(app) as employer, TestClient(app) as candidate:
        employer_id = register(employer, "employer", "employer2@example.invalid")
        candidate_id = register(candidate, "candidate", "candidate2@example.invalid")
        vacancy_id = create_vacancy_and_resume(app, employer_id, candidate_id)
        with database(app.state.db_path) as db:
            invitation_id = db.execute(
                """INSERT INTO invitations(vacancy_id,candidate_id,employer_id,price_rub)
                   VALUES(?,?,?,?)""",
                (vacancy_id, candidate_id, employer_id, 0),
            ).lastrowid

        assert any(j["id"] == vacancy_id for j in candidate.get("/api/jobs").json()["jobs"])
        assert candidate.get(f"/api/jobs/{vacancy_id}").status_code == 200
        assert candidate.get(f"/api/companies/{employer_id}").status_code == 200
        assert candidate.get(f"/employers/{employer_id}").status_code == 200
        directory_before = candidate.get("/employers")
        assert directory_before.status_code == 200
        assert "Тестовая компания" in directory_before.text
        request_restriction(employer, "deletion")

        assert employer.get("/api/me").status_code == 200
        assert employer.get("/api/account/data-export").status_code == 200
        # Previously sent invitations may be declined, but new consent cannot
        # be accepted while the employer is under an active restriction.
        invitation_route = f"/api/candidate/invitations/{invitation_id}/respond"
        assert candidate.post(invitation_route, headers=XHR, json={
            "decision": "accepted", "share_consent": True,
        }).status_code == 409
        declined = candidate.post(invitation_route, headers=XHR, json={
            "decision": "declined", "share_consent": False,
        })
        assert declined.status_code == 200, declined.text
        assert employer.get("/api/employer/vacancies").status_code == 200
        assert employer.get(
            f"/api/employer/vacancies/{vacancy_id}/matches"
        ).status_code == 409
        assert employer.post(
            "/api/employer/invitations", headers=XHR,
            json={"vacancy_id": vacancy_id, "candidate_id": candidate_id},
        ).status_code == 409
        assert all(j["id"] != vacancy_id for j in candidate.get("/api/jobs").json()["jobs"])
        assert candidate.get(f"/api/jobs/{vacancy_id}").status_code == 404
        assert candidate.get(f"/api/companies/{employer_id}").status_code == 404
        assert candidate.get(f"/employers/{employer_id}").status_code == 404
        directory_after = candidate.get("/employers")
        assert directory_after.status_code == 200
        assert directory_after.headers.get("cache-control") == "no-store"
        assert "Тестовая компания" not in directory_after.text
        assert candidate.post(
            "/api/candidate/applications", headers=XHR,
            json={"vacancy_id": vacancy_id},
        ).status_code == 404

        # Restriction is not erasure: linked rows survive pending review.
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM users WHERE id=?", (employer_id,)).fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()[0] == 1

