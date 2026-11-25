"""Candidate-owned saved search and notification regression (fictional data)."""
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.privacy_disposal import impact_preview

XHR = {"X-Requested-With": "OPYT50"}
ROOT = "/api/candidate/saved-searches"


def register(client, role, email):
    payload = {"role": role, "name": "Учебный участник", "email": email,
               "password": "SavedSearchTest2026!Secure"}
    if role == "employer":
        payload["company_name"] = "Учебная компания"
    response = client.post("/api/register", headers=XHR, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def vacancy(app, employer_id, title="Кладовщик", city="Москва", status="open"):
    with database(app.state.db_path) as db:
        return db.execute(
            """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,status)
               VALUES(?,?,?,?,?,?)""",
            (employer_id, title, city, 50000, 90000, status),
        ).lastrowid


def test_subscription_counts_current_matches_without_marking_on_read(tmp_path):
    app = create_app(str(tmp_path / "searches.db"))
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as employer:
        cid = register(owner, "candidate", "owner-search@example.invalid")
        register(other, "candidate", "other-search@example.invalid")
        eid = register(employer, "employer", "employer-search@example.invalid")
        first = vacancy(app, eid)
        vacancy(app, eid, city="Казань")
        vacancy(app, eid, status="closed")
        with database(app.state.db_path) as db:
            mail_before = db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]
        assert employer.get(ROOT).status_code == 403
        with TestClient(app) as guest:
            assert guest.get(ROOT).status_code == 401

        filters = {"q": "кладовщик", "city": "Москва", "salary_min": 60000, "alerts_enabled": True}
        created = owner.post(ROOT, headers=XHR, json=filters)
        assert created.status_code == 201, created.text
        assert created.json()["created"] is True
        search = created.json()["search"]
        key = search["key"]
        url = ROOT + "/" + key
        assert search["new_count"] == 0
        duplicate = owner.post(ROOT, headers=XHR, json={**filters, "q": "КЛАДОВЩИК", "alerts_enabled": False})
        assert duplicate.status_code == 201
        assert duplicate.json()["created"] is False
        assert duplicate.json()["search"]["key"] == key
        assert duplicate.json()["search"]["alerts_enabled"] is True

        assert other.get(ROOT).json()["searches"] == []
        assert other.get(url + "/results").status_code == 404
        assert other.patch(url + "/alerts", headers=XHR, json={"enabled": False, "revision": 1}).status_code == 404
        assert other.delete(url, headers=XHR).status_code == 404

        second = vacancy(app, eid, title="Кладовщик смены")
        hidden = vacancy(app, eid, title="Кладовщик на проверке")
        with database(app.state.db_path) as db:
            db.execute("INSERT INTO vacancy_moderation(vacancy_id,status) VALUES(?,'pending')", (hidden,))
        result = owner.get(url + "/results")
        assert result.status_code == 200, result.text
        assert "no-store" in result.headers["cache-control"]
        shown = result.json()
        assert {job["id"] for job in shown["jobs"]} == {first, second}
        assert shown["new_ids"] == [second]
        assert owner.get(ROOT).json()["searches"][0]["new_count"] == 1
        assert owner.get(url + "/results").json()["new_ids"] == [second]

        third = vacancy(app, eid, title="Кладовщик новой смены")
        marked = owner.post(url + "/review", headers=XHR,
                            json={"revision": shown["search"]["revision"],
                                  "vacancy_ids": [job["id"] for job in shown["jobs"]]})
        assert marked.status_code == 200, marked.text
        assert marked.json()["search"]["new_count"] == 1
        assert owner.get(url + "/results").json()["new_ids"] == [third]
        assert owner.post(url + "/review", headers=XHR,
                          json={"revision": 1, "vacancy_ids": [third]}).status_code == 409

        rev = marked.json()["search"]["revision"]
        off = owner.patch(url + "/alerts", headers=XHR, json={"enabled": False, "revision": rev})
        assert off.status_code == 200, off.text
        assert off.json()["search"]["new_count"] is None
        fourth = vacancy(app, eid, title="Кладовщик вечерней смены")
        assert owner.get(url + "/results").json()["new_ids"] == []
        on = owner.patch(url + "/alerts", headers=XHR,
                         json={"enabled": True, "revision": off.json()["search"]["revision"]})
        assert on.status_code == 200, on.text
        assert on.json()["search"]["new_count"] == 0
        assert fourth in [job["id"] for job in owner.get(url + "/results").json()["jobs"]]

        # A formerly unpublished vacancy can enter the current matching set.
        with database(app.state.db_path) as db:
            db.execute("UPDATE vacancy_moderation SET status='approved' WHERE vacancy_id=?", (hidden,))
        assert owner.get(url + "/results").json()["new_ids"] == [hidden]
        exported = owner.get("/api/account/data-export").json()["sections"]["my_saved_searches"]
        assert len(exported) == 1 and exported[0]["search_key"] == key
        assert exported[0]["alerts_enabled"] is True
        assert hidden not in exported[0]["reviewed_vacancy_ids"]
        assert other.get("/api/account/data-export").json()["sections"]["my_saved_searches"] == []
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == mail_before
            assert db.execute("SELECT COUNT(*) FROM candidate_saved_searches WHERE candidate_id=?", (cid,)).fetchone()[0] == 1
        assert owner.delete(url, headers=XHR).status_code == 200
        assert owner.get(url + "/results").status_code == 404


def test_limits_and_restriction_preserve_private_filters_without_matching(tmp_path):
    app = create_app(str(tmp_path / "search-limits.db"))
    with TestClient(app) as owner:
        register(owner, "candidate", "limits-search@example.invalid")
        for invalid in ({"salary_min": -1}, {"salary_min": True}, {"schedule": "invalid"},
                        {"q": "private@example.invalid"}, {"city": "8 999 123-45-67"},
                        {"q": "a" * 121}, {"alerts_enabled": "yes"}, {"owner_id": 2}):
            response = owner.post(ROOT, headers=XHR, json=invalid)
            assert response.status_code == 422, (invalid, response.text)
        for index in range(10):
            created = owner.post(ROOT, headers=XHR, json={"q": f"Профессия {index}", "alerts_enabled": True})
            assert created.status_code == 201, created.text
        assert owner.post(ROOT, headers=XHR, json={"q": "Ещё одна"}).status_code == 409
        searches = owner.get(ROOT).json()["searches"]
        assert len(searches) == 10
        key = searches[0]["key"]
        assert owner.delete(ROOT + "/" + key, headers=XHR).status_code == 200
        recreated = owner.post(ROOT, headers=XHR, json={"q": "Профессия 0", "alerts_enabled": True})
        assert recreated.status_code == 201
        assert recreated.json()["search"]["key"] != key
        key = recreated.json()["search"]["key"]
        request = owner.post("/api/account/privacy-requests", headers=XHR,
                             json={"kind": "stop_processing"})
        assert request.status_code == 201, request.text
        data = owner.get(ROOT).json()
        assert data["restricted"] is True
        assert len(data["searches"]) == 10
        assert all(search["new_count"] is None for search in data["searches"])
        assert owner.get(ROOT + "/" + key + "/results").status_code == 409
        assert owner.post(ROOT, headers=XHR, json={"q": "Другое"}).status_code == 409
        assert len(owner.get("/api/account/data-export").json()["sections"]["my_saved_searches"]) == 10
        with database(app.state.db_path) as db:
            preview = impact_preview(db, request.json()["request"]["request_key"])
            assert preview["counts"]["saved_searches"] == 10
