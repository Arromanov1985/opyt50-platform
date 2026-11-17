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
    if role == "candidate":
        profile = client.put("/api/candidate/profile", json={
            "profession": "Кладовщик", "city": "Подольск",
            "skills": "1С", "salary_min": 65000,
            "schedule": "Сменный", "employment": "Полная",
            "phone": "", "about": "Тестовый опыт", "is_active": True,
        }, headers=HDR)
        assert profile.status_code == 200, profile.text
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
        assert u["relationship"] == "application"
        employer_history = owner.get(f"/api/employer/vacancies/{job_id}/updates")
        assert employer_history.status_code == 200, employer_history.text
        history = employer_history.json()
        assert history["vacancy_id"] == job_id
        assert history["total_count"] == 1
        assert history["updates"][0]["changes"] == u["changes"]
        assert history["updates"][0]["recipients_total"] == 1
        assert "recipients_read" not in history["updates"][0]
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
        history = owner.get(f"/api/employer/vacancies/{job_id}/updates").json()
        assert history["total_count"] == 2
        assert len(history["updates"]) == 2
        assert [item["recipients_total"] for item in history["updates"]] == [2, 1]
        assert history["updates"][0]["changes"]["salary_max"]["after"] == 120000

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
        assert "recipients_read" not in owner.get(
            f"/api/employer/vacancies/{job_id}/updates"
        ).json()["updates"][1]  # Candidate's read status is private.

        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM vacancy_updates").fetchone()[0] == 2
            assert db.execute("SELECT COUNT(*) FROM vacancy_update_recipients").fetchone()[0] == 3
            assert db.execute("SELECT COUNT(*) FROM email_outbox WHERE event LIKE ?", ("%vacancy_update%",)).fetchone()[0] == 0
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



def test_change_history_owner_only_invitation_next_step_and_zero_updates(app):
    with TestClient(app) as owner, TestClient(app) as stranger, TestClient(app) as candidate:
        register(owner, "employer", "Мария Демо", "history-owner@example.test")
        register(stranger, "employer", "Другой Работодатель", "history-stranger@example.test")
        cid = register(candidate, "candidate", "Соискатель Демо", "invite-only@example.test")
        job_id = create_job(owner)
        history_url = f"/api/employer/vacancies/{job_id}/updates"
        empty = owner.get(history_url)
        assert empty.status_code == 200, empty.text
        assert empty.json() == {"vacancy_id": job_id, "total_count": 0, "has_more": False, "next_cursor": None, "updates": []}
        assert stranger.get(history_url).status_code == 404
        assert candidate.get(history_url).status_code == 403
        assert owner.get("/api/employer/vacancies/999999/updates").status_code == 404

        # Candidate was invited directly and never applied for this vacancy.
        invite = post(owner, "/api/employer/invitations", {
            "vacancy_id": job_id, "candidate_id": cid,
        })
        assert invite.status_code == 201, invite.text
        assert edit(owner, job_id, salary_min=76000).status_code == 200
        notice = notifications(candidate)
        assert notice["unread_count"] == 1
        assert len(notice["updates"]) == 1
        assert notice["updates"][0]["relationship"] == "invitation"
        assert notice["updates"][0]["changes"]["salary_min"] == {
            "before": 70000, "after": 76000,
        }

        after = owner.get(history_url)
        assert after.status_code == 200
        assert after.json()["total_count"] == 1
        assert after.json()["updates"][0]["recipients_total"] == 1
        assert "read_at" not in after.json()["updates"][0]
        assert "recipients_read" not in after.json()["updates"][0]
        assert stranger.get(history_url).status_code == 404
        assert candidate.get(history_url).status_code == 403


def test_candidate_inbox_history_over_100_and_filters(app):
    """More than 100 notices stay reachable and read actions remain private."""
    import json
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as stranger:
        employer_id = register(employer, "employer", "Работодатель", "pages-owner@example.test")
        candidate_id = register(candidate, "candidate", "Кандидат", "pages-candidate@example.test")
        register(stranger, "candidate", "Другой", "pages-stranger@example.test")
        job_id = create_job(employer)
        with database(app.state.db_path) as db:
            for n in range(125):
                inserted = db.execute(
                    "INSERT INTO vacancy_updates(vacancy_id,employer_id,changes_json) VALUES(?,?,?)",
                    (job_id, employer_id,
                     json.dumps({"salary_min": {"before": 70000, "after": 70001+n}})),
                )
                db.execute(
                    "INSERT INTO vacancy_update_recipients(update_id,candidate_id,read_at) VALUES(?,?,?)",
                    (inserted.lastrowid, candidate_id,
                     "2026-11-17 10:00:00" if n % 4 == 0 else None),
                )
            db.commit()
        first = notifications(candidate)
        assert (first["total_count"], first["unread_count"], first["read_count"]) == (125, 93, 32)
        assert len(first["updates"]) == 20
        assert first["has_more"] and first["next_cursor"] == first["updates"][-1]["id"]
        for selection, expected in [("all", 125), ("unread", 93), ("read", 32)]:
            cursor = None
            collected = []
            while True:
                params = {"filter": selection, "limit": 17}
                if cursor is not None:
                    params["before_id"] = cursor
                response = candidate.get("/api/candidate/vacancy-updates", params=params)
                assert response.status_code == 200, response.text
                page = response.json()
                assert page["unread_count"] == 93 and page["total_count"] == 125
                collected.extend(row["id"] for row in page["updates"])
                if selection != "all":
                    assert all((row["read_at"] is None) == (selection == "unread")
                               for row in page["updates"])
                if not page["has_more"]:
                    assert page["next_cursor"] is None
                    break
                cursor = page["next_cursor"]
            assert len(collected) == expected
            assert len(set(collected)) == expected
            assert collected == sorted(collected, reverse=True)
            if selection == "unread":
                oldest_unread = collected[-1]
        assert post(candidate, f"/api/candidate/vacancy-updates/{oldest_unread}/read").status_code == 200
        assert notifications(candidate)["unread_count"] == 92
        assert candidate.get("/api/candidate/vacancy-updates",
                             params={"filter": "read"}).json()["read_count"] == 33
        assert notifications(stranger)["total_count"] == 0
        assert notifications(stranger)["updates"] == []
        assert employer.get("/api/candidate/vacancy-updates").status_code == 403
        for invalid in [{"filter": "bad"}, {"limit": 0}, {"limit": 51},
                        {"before_id": 0}, {"before_id": -1}]:
            assert candidate.get("/api/candidate/vacancy-updates",params=invalid).status_code == 422


def test_employer_history_all_pages_and_owner_scoping(app):
    """Employers can inspect all historical changes without candidate read receipts."""
    import json
    with TestClient(app) as employer, TestClient(app) as stranger, TestClient(app) as candidate:
        owner_id = register(employer, "employer", "Работодатель", "history-owner125@example.test")
        register(stranger, "employer", "Чужой работодатель", "history-stranger125@example.test")
        candidate_id = register(candidate, "candidate", "Соискатель", "history-candidate125@example.test")
        job_id = create_job(employer)
        other_job = create_job(employer)
        with database(app.state.db_path) as db:
            for n in range(125):
                inserted = db.execute(
                    "INSERT INTO vacancy_updates(vacancy_id,employer_id,changes_json) VALUES(?,?,?)",
                    (job_id, owner_id, json.dumps({"salary_min": {"before": 70000, "after": 70001+n}})),
                )
                if n % 2 == 0:
                    db.execute(
                        "INSERT INTO vacancy_update_recipients(update_id,candidate_id,read_at) VALUES(?,?,?)",
                        (inserted.lastrowid, candidate_id, "2026-11-17 10:00:00" if n % 4 == 0 else None),
                    )
            # Another vacancy must not appear in this history.
            db.execute(
                "INSERT INTO vacancy_updates(vacancy_id,employer_id,changes_json) VALUES(?,?,?)",
                (other_job, owner_id, '{"title":{"before":"A","after":"B"}}'),
            )
            db.commit()

        url = f"/api/employer/vacancies/{job_id}/updates"
        first = employer.get(url)
        assert first.status_code == 200, first.text
        data = first.json()
        assert data["total_count"] == 125
        assert len(data["updates"]) == 20
        assert data["has_more"] is True
        assert data["next_cursor"] == data["updates"][-1]["id"]
        collected = []
        cursor = None
        while True:
            params = {"limit": 17}
            if cursor is not None:
                params["before_id"] = cursor
            response = employer.get(url, params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["total_count"] == 125
            collected.extend(item["id"] for item in page["updates"])
            assert all("read_at" not in item and "candidate_id" not in item
                       and "recipients_read" not in item for item in page["updates"])
            if not page["has_more"]:
                assert page["next_cursor"] is None
                break
            cursor = page["next_cursor"]
        assert len(collected) == len(set(collected)) == 125
        assert collected == sorted(collected, reverse=True)
        assert stranger.get(url).status_code == 404
        assert candidate.get(url).status_code == 403
        assert employer.get(f"/api/employer/vacancies/{other_job}/updates").json()["total_count"] == 1
        for invalid in [{"limit": 0}, {"limit": 51}, {"before_id": 0}, {"before_id": -1}]:
            assert employer.get(url, params=invalid).status_code == 422
