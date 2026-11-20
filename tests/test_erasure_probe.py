"""Isolation-only erasure probe: a transaction is ALWAYS rolled back.

The probe uses a pytest temporary SQLite database with invented accounts.
It is NOT an account deletion endpoint or a production runbook.
"""
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}


def register(client, email, role, company=None):
    data = {
        "email": email, "password": "SyntheticPass2026Strong!",
        "name": "Вымышленный участник", "role": role,
    }
    if company:
        data["company_name"] = company
    response = client.post("/api/register", json=data, headers=XHR)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def test_erasure_probe_rolls_back_even_when_foreign_keys_prevent_deletion(tmp_path: Path):
    # TestClient never receives a production DATABASE_URL here.
    app = create_app(str(tmp_path / "isolated-erasure-probe.db"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        candidate_id = register(candidate, "synthetic-candidate@example.invalid", "candidate")
        employer_id = register(
            employer, "synthetic-employer@example.invalid", "employer", "Компания-муляж"
        )
        with database(app.state.db_path) as db:
            vacancy_id = db.execute(
                """INSERT INTO vacancies
                   (employer_id,title,city,salary_min,salary_max,skills)
                   VALUES(?,?,?,?,?,?)""",
                (employer_id, "Тестовая работа", "Москва", 10000, 30000, "Тест"),
            ).lastrowid
            application_id = db.execute(
                "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)",
                (vacancy_id, candidate_id),
            ).lastrowid
            db.execute(
                """INSERT INTO application_events(application_id,event)
                   VALUES(?,'applied')""",
                (application_id,),
            )
            before = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("users", "vacancies", "job_applications", "application_events")
            }
            db.execute("SAVEPOINT isolated_probe")
            try:
                # Observe possible cascade behavior in disposable test storage ONLY.
                for user_id in (candidate_id, employer_id):
                    try:
                        db.execute("DELETE FROM users WHERE id=?", (user_id,))
                    except sqlite3.IntegrityError:
                        # A real cleanup must address dependent records first.
                        pass
            finally:
                db.execute("ROLLBACK TO SAVEPOINT isolated_probe")
                db.execute("RELEASE SAVEPOINT isolated_probe")

            after = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }
            assert after == before
            assert db.execute(
                "SELECT COUNT(*) FROM users WHERE id IN (?,?)",
                (candidate_id, employer_id),
            ).fetchone()[0] == 2
            assert db.execute(
                "SELECT COUNT(*) FROM job_applications WHERE id=?", (application_id,)
            ).fetchone()[0] == 1
