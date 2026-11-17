"""Private draft flow: access control, version conflicts and idempotent publication."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}


def register(client, email, role):
    payload = {
        "email": email, "password": "StrongPass2026!",
        "name": "Тестовый Пользователь", "role": role,
    }
    if role == "employer":
        payload["company_name"] = "Демо Компания"
    response = client.post("/api/register", json=payload, headers=XHR)
    assert response.status_code == 201, response.text


def fields(**extra):
    return {
        "title": "Кладовщик", "city": "Подольск",
        "salary_min": "70000", "salary_max": "90000",
        "schedule": "Сменный", "employment": "Полная",
        "skills": "1С", "responsibilities": "Учёт товаров",
        "requirements": "Знание 1С", "conditions": "График 2/2",
    } | extra


def test_private_drafts_and_publish_once(tmp_path: Path):
    app = create_app(str(tmp_path / "drafts.db"))
    with TestClient(app) as employer, TestClient(app) as other, TestClient(app) as candidate:
        register(employer, "draft-owner@example.test", "employer")
        register(other, "draft-other@example.test", "employer")
        register(candidate, "draft-candidate@example.test", "candidate")
        created = employer.post("/api/employer/vacancy-drafts", json={"fields": {"title": "Кладовщик"}}, headers=XHR)
        assert created.status_code == 201, created.text
        draft = created.json()
        did = draft["id"]
        assert candidate.get("/api/employer/vacancy-drafts").status_code == 403
        assert other.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(), "expected_version": draft["version"]
        }, headers=XHR).status_code == 404
        assert candidate.get("/api/jobs").json()["jobs"] == []
        updated = employer.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(), "expected_version": draft["version"]
        }, headers=XHR)
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == draft["version"] + 1
        stale = employer.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(title="Старый заголовок"), "expected_version": draft["version"]
        }, headers=XHR)
        assert stale.status_code == 409
        assert candidate.get("/api/jobs").json()["jobs"] == []
        published = employer.post(f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR)
        assert published.status_code == 200, published.text
        jid = published.json()["id"]
        second = employer.post(f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR)
        assert second.status_code == 200
        assert second.json()["id"] == jid
        assert second.json()["already_published"] is True
        assert len(employer.get("/api/employer/vacancies").json()["jobs"]) == 1
        assert employer.get("/api/employer/vacancy-drafts").json()["drafts"] == []
        assert other.delete(f"/api/employer/vacancy-drafts/{did}", headers=XHR).status_code == 404


def test_incomplete_draft_cannot_publish(tmp_path: Path):
    app = create_app(str(tmp_path / "partial.db"))
    with TestClient(app) as employer:
        register(employer, "draft-partial@example.test", "employer")
        response = employer.post("/api/employer/vacancy-drafts", json={"fields": {"title": "Кладовщик"}}, headers=XHR)
        did = response.json()["id"]
        assert employer.post(f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR).status_code == 422
        assert employer.get("/api/employer/vacancy-drafts").json()["drafts"][0]["id"] == did
        assert employer.get("/api/employer/vacancies").json()["jobs"] == []
        incomplete = employer.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(requirements=""), "expected_version": 1
        }, headers=XHR)
        assert incomplete.status_code == 200
        still_incomplete = employer.post(
            f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR,
        )
        assert still_incomplete.status_code == 422


def test_draft_save_is_idempotent_after_lost_response(tmp_path: Path):
    """A retry with the previous version must not create a false conflict."""
    app = create_app(str(tmp_path / "retry.db"))
    with TestClient(app) as employer, TestClient(app) as other, TestClient(app) as candidate:
        register(employer, "draft-retry@example.test", "employer")
        register(other, "draft-other-retry@example.test", "employer")
        register(candidate, "draft-candidate-retry@example.test", "candidate")
        created = employer.post(
            "/api/employer/vacancy-drafts",
            json={"fields": {"title": "Склад"}}, headers=XHR,
        )
        assert created.status_code == 201, created.text
        did = created.json()["id"]
        draft_url = f"/api/employer/vacancy-drafts/{did}"
        assert other.get(draft_url).status_code == 404
        assert candidate.get(draft_url).status_code == 403
        initial = employer.get(draft_url)
        assert initial.status_code == 200
        assert initial.headers["cache-control"] == "no-store"
        assert initial.json()["fields"]["title"] == "Склад"

        payload = {"fields": fields(), "expected_version": 1}
        saved = employer.put(draft_url, json=payload, headers=XHR)
        assert saved.status_code == 200 and saved.json()["version"] == 2
        # Client lost the HTTP response and resends the same payload.
        repeated = employer.put(draft_url, json=payload, headers=XHR)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["version"] == 2
        assert repeated.json()["fields"] == fields()
        assert employer.get(draft_url).json()["version"] == 2

        # A different payload from a stale device still fails safely.
        changed_on_other_device = employer.put(
            draft_url,
            json={"fields": fields(title="Складской оператор"), "expected_version": 2},
            headers=XHR,
        )
        assert changed_on_other_device.status_code == 200
        assert changed_on_other_device.json()["version"] == 3
        stale_overwrite = employer.put(
            draft_url,
            json={"fields": fields(title="Несвежая копия"), "expected_version": 2},
            headers=XHR,
        )
        assert stale_overwrite.status_code == 409
        assert employer.get(draft_url).json()["fields"]["title"] == "Складской оператор"
        assert candidate.get("/api/jobs").json()["jobs"] == []



def test_first_create_replay_is_idempotent_and_owner_scoped(tmp_path: Path):
    """Retrying POST after a lost HTTP response reuses the same draft ID."""
    app = create_app(str(tmp_path / "first-create-retry.db"))
    key = "f7ea5179-84b7-4363-8e39-9bbc7a958eb2"
    payload = {"fields": {"title": "Помощник на складе", "city": "Подольск"},
               "request_key": key}
    with TestClient(app) as employer, TestClient(app) as other, TestClient(app) as candidate:
        register(employer, "create-owner@example.test", "employer")
        register(other, "create-other@example.test", "employer")
        register(candidate, "create-candidate@example.test", "candidate")
        first = employer.post("/api/employer/vacancy-drafts", json=payload, headers=XHR)
        assert first.status_code == 201, first.text
        did = first.json()["id"]
        assert first.json()["version"] == 1

        # The first transaction committed but the browser never saw the 201.
        replay = employer.post("/api/employer/vacancy-drafts", json=payload, headers=XHR)
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()
        assert len(employer.get("/api/employer/vacancy-drafts").json()["drafts"]) == 1

        request_url = f"/api/employer/vacancy-drafts/by-request/{key}"
        assert employer.get(request_url).json()["id"] == did
        assert other.get(request_url).status_code == 404
        assert candidate.get(request_url).status_code == 403

        # A changed payload must not silently overwrite the original create.
        changed = employer.post("/api/employer/vacancy-drafts", json={
            **payload, "fields": {"title": "Изменённый заголовок"}
        }, headers=XHR)
        assert changed.status_code == 409
        assert employer.get(request_url).json()["fields"] == payload["fields"]
        assert len(employer.get("/api/employer/vacancy-drafts").json()["drafts"]) == 1

        # The same random key has a separate namespace for each employer.
        other_created = other.post("/api/employer/vacancy-drafts", json=payload, headers=XHR)
        assert other_created.status_code == 201
        assert other_created.json()["id"] != did
        assert employer.get(request_url).json()["id"] == did

        # A deleted draft is NOT recreated by a delayed retry of its first POST.
        deleted = employer.delete(f"/api/employer/vacancy-drafts/{did}", headers=XHR)
        assert deleted.status_code == 200
        assert employer.post("/api/employer/vacancy-drafts", json=payload, headers=XHR).status_code == 410
        assert employer.get(request_url).status_code == 410
        assert employer.get("/api/employer/vacancy-drafts").json()["drafts"] == []


def test_first_create_key_survives_restart_and_rejects_invalid_uuid(tmp_path: Path):
    path = tmp_path / "restart-create.db"
    key = "f412d50a-4e6d-47c0-9fb5-2cf400001997"
    payload = {"fields": {"title": "Временная вакансия"}, "request_key": key}
    with TestClient(create_app(str(path))) as employer:
        register(employer, "create-restart@example.test", "employer")
        first = employer.post("/api/employer/vacancy-drafts", json=payload, headers=XHR)
        assert first.status_code == 201
        did = first.json()["id"]
        invalid = employer.post("/api/employer/vacancy-drafts", json={
            "fields": {"title": "Раз"}, "request_key": "not-a-uuid",
        }, headers=XHR)
        assert invalid.status_code == 422

    with TestClient(create_app(str(path))) as reopened:
        login = reopened.post("/api/login", json={
            "email": "create-restart@example.test", "password": "StrongPass2026!"
        }, headers=XHR)
        assert login.status_code == 200, login.text
        retry = reopened.post("/api/employer/vacancy-drafts", json=payload, headers=XHR)
        assert retry.status_code == 200
        assert retry.json()["id"] == did
        assert len(reopened.get("/api/employer/vacancy-drafts").json()["drafts"]) == 1
