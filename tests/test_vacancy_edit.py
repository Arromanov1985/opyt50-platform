"""Release 0.3 vacancy edits: safe updates without duplicates or lost applications.

Test data is entirely fictional. No third-party email or payment integration.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "edit-vacancies.db"))


def post(client, route, data):
    return client.post(route, json=data, headers=XHR)


def register(client, email, role, company="Компания Демо"):
    payload = {
        "email": email, "role": role, "name": "Тестовый Пользователь",
        "password": "StrongPass2026!",
    }
    if role == "employer":
        payload["company_name"] = company
    response = post(client, "/api/register", payload)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def job_payload(**changes):
    original = {
        "title": "Кладовщик",
        "city": "Подольск",
        "salary_min": 70000,
        "salary_max": 90000,
        "schedule": "Сменный",
        "employment": "Полная",
        "skills": "1С, склад",
        "description": (
            "Обязанности:\nУчёт товаров\n\n"
            "Требования:\nЗнание 1С\n\n"
            "Условия работы:\nГрафик 2/2"
        ),
    }
    return original | changes


def create_job(client, **changes):
    response = post(client, "/api/employer/vacancies", job_payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def owned_job(client, job_id):
    response = client.get("/api/employer/vacancies")
    assert response.status_code == 200, response.text
    return next(job for job in response.json()["jobs"] if job["id"] == job_id)


def edited_body(job, **changes):
    return {
        key: job[key]
        for key in ("title", "city", "salary_min", "salary_max", "schedule",
                    "employment", "skills", "description")
    } | {"expected_revision": job["revision"]} | changes


def patch(client, job_id, body):
    return client.patch(f"/api/employer/vacancies/{job_id}", json=body, headers=XHR)


def test_edit_keeps_vacancy_applications_invitations_and_consent(app):
    with TestClient(app) as employer, TestClient(app) as candidate:
        register(employer, "employer@demo.example", "employer")
        cid = register(candidate, "candidate@demo.example", "candidate")
        profile = candidate.put("/api/candidate/profile", json={
            "profession": "Кладовщик", "city": "Подольск",
            "skills": "склад, 1С", "salary_min": 65000,
            "schedule": "Сменный", "employment": "Полная",
            "about": "Демонстрационный опыт", "phone": "+70000000001", "is_active": True,
        }, headers=XHR)
        assert profile.status_code == 200, profile.text
        jid = create_job(employer)
        applied = post(candidate, "/api/candidate/applications", {"vacancy_id": jid})
        assert applied.status_code == 201, applied.text
        application_id = applied.json()["id"]
        invite = post(employer, f"/api/employer/applications/{application_id}/interest", {})
        assert invite.status_code == 200, invite.text
        invitation_id = invite.json()["invitation_id"]
        consent = post(candidate, f"/api/candidate/invitations/{invitation_id}/respond", {
            "decision": "accepted", "share_consent": True,
        })
        assert consent.status_code == 200, consent.text

        before = owned_job(employer, jid)
        assert len(before["revision"]) == 64
        replacement = edited_body(
            before,
            title="Кладовщик ночной смены",
            salary_min=82000,
            salary_max=110000,
            description=job_payload()["description"].replace("График 2/2", "График 3/3"),
        )
        response = patch(employer, jid, replacement)
        assert response.status_code == 200, response.text
        edited = response.json()["job"]
        assert edited["id"] == jid
        assert edited["status"] == "open"
        assert edited["created_at"] == before["created_at"]
        assert edited["revision"] != before["revision"]
        assert edited["salary_min"] == 82000
        assert "График 3/3" in edited["description"]

        rows = employer.get("/api/employer/vacancies").json()["jobs"]
        assert len(rows) == 1 and rows[0]["id"] == jid
        assert len(candidate.get("/api/candidate/applications").json()["applications"]) == 1
        assert len(employer.get("/api/employer/applications").json()["applications"]) == 1
        inv = candidate.get("/api/candidate/invitations").json()["invitations"]
        assert len(inv) == 1 and inv[0]["status"] == "accepted"
        jobs = candidate.get("/api/jobs").json()["jobs"]
        assert any(row["id"] == jid and row["title"] == "Кладовщик ночной смены" for row in jobs)
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 1
            assert db.execute(
                "SELECT id FROM job_applications WHERE vacancy_id=?", (jid,)
            ).fetchone()[0] == application_id
            assert db.execute(
                "SELECT id, share_consent FROM invitations WHERE vacancy_id=?", (jid,)
            ).fetchone()["share_consent"] == 1


def test_only_owner_can_edit_and_stale_revisions_are_rejected(app):
    with TestClient(app) as owner, TestClient(app) as stranger, TestClient(app) as candidate:
        register(owner, "first@demo.example", "employer")
        register(stranger, "second@demo.example", "employer")
        register(candidate, "candidate@demo.example", "candidate")
        jid = create_job(owner)
        old = owned_job(owner, jid)
        body = edited_body(old, salary_min=80000)
        assert patch(candidate, jid, body).status_code == 403
        assert patch(stranger, jid, body).status_code == 404
        assert patch(owner, 9999999, body).status_code == 404
        assert patch(owner, jid, {**body, "expected_revision": "bad"}).status_code == 422
        assert patch(owner, jid, {**body, "salary_max": 10}).status_code == 422
        assert patch(owner, jid, {**body, "title": "  "}).status_code == 422
        assert patch(owner, jid, {**body, "city": "  "}).status_code == 422
        assert patch(owner, jid, {**body, "schedule": "Непонятно"}).status_code == 422

        first = patch(owner, jid, edited_body(old, salary_min=80000))
        assert first.status_code == 200, first.text
        stale = patch(owner, jid, edited_body(old, salary_min=85000))
        assert stale.status_code == 409, stale.text
        after = owned_job(owner, jid)
        assert after["salary_min"] == 80000
        assert after["salary_max"] == 90000
        # The new revision works, so the conflict is recoverable with a refresh.
        corrected = patch(owner, jid, edited_body(after, salary_min=81000))
        assert corrected.status_code == 200
        assert owned_job(owner, jid)["salary_min"] == 81000


def test_legacy_description_and_closed_status_survive_edit(app):
    with TestClient(app) as employer, TestClient(app) as visitor:
        register(employer, "employer@demo.example", "employer")
        jid = create_job(employer, description="Склад. Старое описание без заголовков.")
        before = owned_job(employer, jid)
        status = employer.patch(
            f"/api/employer/vacancies/{jid}/status",
            json={"status": "closed"}, headers=XHR,
        )
        assert status.status_code == 200
        refreshed = owned_job(employer, jid)
        # Status change itself invalidates a stale content revision.
        assert patch(employer, jid, edited_body(before, salary_min=76000)).status_code == 409
        update = patch(employer, jid, edited_body(refreshed, salary_min=76000))
        assert update.status_code == 200, update.text
        after = update.json()["job"]
        assert after["status"] == "closed"
        assert after["description"] == "Склад. Старое описание без заголовков."
        assert after["id"] == jid
        assert all(row["id"] != jid for row in visitor.get("/api/jobs").json()["jobs"])
        assert len(employer.get("/api/employer/vacancies").json()["jobs"]) == 1
