"""Release 0.3 candidate notices when employer edits an already applied-for vacancy.

No real contacts, emails, SMS or payment services.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db import database

HDR = {"X-Requested-With": "OPYT50"}


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "notices.db"))


def post(client, path, data=None):
    return client.post(path, json=data, headers=HDR)


def register(client, role, name, email):
    d = {"role": role, "name": name, "email": email, "password": "StrongPass2026!"}
    if role == "employer":
        d["company_name"] = "Тестовая компания"
    r = post(client, "/api/register", d)
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"]


def create_job(client):
    payload = {
        "title": "Кладовщик", "city": "Подольск",
        "salary_min": 70000, "salary_max": 100000,
        "schedule": "Сменный", "employment": "Полная", "skills": "1С",
        "description": "Тестовые обязанности, условия и требования",
    }
    r = post(client, "/api/employer/vacancies", payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get_job(client, job_id):
    r = client.get("/api/employer/vacancies")
    assert r.status_code == 200, r.text
    return next(j for j in r.json()["jobs"] if j["id"] == job_id)


def edit(client, job_id, **changes):
    job = get_job(client, job_id)
    body = {k: job[k] for k in (
        "title", "city", "salary_min", "salary_max",
        "schedule", "employment", "skills", "description",
    )}
    body["expected_revision"] = job["revision"]
    return client.patch(
        f"/api/employer/vacancies/{job_id}",
        json=body | changes, headers=HDR,
    )


def notifications(client):
    r = client.get("/api/candidate/vacancy-updates")
    assert r.status_code == 200, r.text
    return r.json()


def test_only_preexisting_active_applicants_receive_edits(app):
    with TestClient(app) as owner, TestClient(app) as applicant, \
         TestClient(app) as withdrawn, TestClient(app) as late:
        register(owner, "employer", "Мария Демо", "owner@demo.example")
        register(applicant, "candidate", "Александр Демо", "one@demo.example")
        register(withdrawn, "candidate", "Наталья Демо", "two@demo.example")
        register(late, "candidate", "Ольга Демо", "late@demo.example")
        job_id = create_job(owner)
        applied = post(applicant, "/api/candidate/applications", {"vacancy_id": job_id})
        assert applied.status_code == 201, applied.text
        withdrawn_application = post(withdrawn, "/api/candidate/applications", {"vacancy_id": job_id})
        assert withdrawn_application.status_code == 201
        stopped = post(withdrawn, f"/api/candidate/applications/{withdrawn_application.json()['id']}/withdraw")
        assert stopped.status_code == 200, stopped.text
        assert notifications(applicant)["updates"] == []
        assert edit(owner, job_id, salary_min=78000, description="Обновлённые условия").status_code == 200

        received = notifications(applicant)
        assert received["unread_count"] == 1
        assert len(received["updates"]) == 1
        u = received["updates"][0]
        assert u["vacancy_id"] == job_id
        assert u["company_name"] == "Тестовая компания"
        assert u["changes"]["salary_min"] == {"before": 70000, "after": 78000}
        assert u["changes"]["description"]["after"] == "Обновлённые условия"
        assert "salary_max" not in u["changes"]
        assert u["read_at"] is None
        assert notifications(withdrawn)["updates"] == []
        assert notifications(late)["updates"] == []

        # Applying after this edit must not reveal previous update history.
        new_app = post(late, "/api/candidate/applications", {"vacancy_id": job_id})
        assert new_app.status_code == 201
        assert notifications(late)["updates"] == []
        assert edit(owner, job_id, salary_max=120000).status_code == 200
        assert notifications(applicant)["unread_count"] == 2
        assert notifications(late)["unread_count"] == 1
        assert notifications(withdrawn)["unread_count"] == 0

        # Ownership of notifications is checked for both listing and read.
        nid = u["id"]
        assert post(late, f"/api/candidate/vacancy-updates/{nid}/read").status_code == 404
        assert post(owner, f"/api/candidate/vacancy-updates/{nid}/read").status_code == 403
        assert owner.get("/api/candidate/vacancy-updates").status_code == 403
        assert post(applicant, f"/api/candidate/vacancy-updates/{nid}/read").status_code == 200
        assert post(applicant, f"/api/candidate/vacancy-updates/{nid}/read").status_code == 200
        read = notifications(applicant)
        assert read["unread_count"] == 1
        assert next(v for v in read["updates"] if v["id"] == nid)["read_at"]
        assert len(read["updates"]) == 2  # Read events stay visible.

        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM vacancy_updates").fetchone()[0] == 2
            assert db.execute("SELECT COUNT(*) FROM vacancy_update_recipients").fetchone()[0] == 3
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] >= 0
            assert db.execute("SELECT COUNT(*) FROM vacancies WHERE id=?", (job_id,)).fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM job_applications WHERE vacancy_id=?", (job_id,)).fetchone()[0] == 3


def test_no_changes_means_no_notification_and_rejected_edit_is_atomic(app):
    with TestClient(app) as owner, TestClient(app) as candidate:
        register(owner, "employer", "Мария Демо", "company@demo.example")
        register(candidate, "candidate", "Александр Демо", "candidate@demo.example")
        jid = create_job(owner)
        assert post(candidate, "/api/candidate/applications", {"vacancy_id": jid}).status_code == 201
        # Empty/no-op edits must not generate noise.
        assert edit(owner, jid).status_code == 200
        assert notifications(candidate)["updates"] == []
        before = get_job(owner, jid)
        body = {k: before[k] for k in (
            "title", "city", "salary_min", "salary_max",
            "schedule", "employment", "skills", "description",
        )} | {"expected_revision": before["revision"], "salary_min": 78000}
        assert edit(owner, jid, salary_max=130000).status_code == 200
        stale = owner.patch(f"/api/employer/vacancies/{jid}",json=body, headers=HDR)
        assert stale.status_code == 409
        assert notifications(candidate)["unread_count"] == 1
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM vacancy_updates").fetchone()[0] == 1
