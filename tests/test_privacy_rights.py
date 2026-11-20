"""Privacy rights request workflow — authenticated, separated and non-destructive."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import active_user, create_app

XHR = {"X-Requested-With": "OPYT50"}


def register(client, email: str, role: str = "candidate"):
    payload = {
        "email": email, "name": "Тестовый участник",
        "role": role, "password": "Unique and safe test 2026",
    }
    if role == "employer":
        payload["company_name"] = "Тестовый работодатель"
    result = client.post("/api/register", headers=XHR, json=payload)
    assert result.status_code == 201, result.text
    return result.json()["user"]["id"]


def send(client, kind="access", **extra):
    return client.post(
        "/api/account/privacy-requests",
        headers=XHR, json={"kind":kind, **extra},
    )


def test_subject_request_is_authenticated_deduplicated_and_does_not_delete(tmp_path):
    app = create_app(str(tmp_path / "rights.sqlite"))
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as guest:
        candidate_id = register(candidate, "rightscandidate@example.invalid")
        register(employer, "rightsemployer@example.invalid", "employer")
        assert guest.get("/api/account/privacy-requests").status_code == 401
        assert send(guest).status_code == 401
        assert candidate.post(
            "/api/account/privacy-requests", json={"kind":"access"}
        ).status_code == 403  # CSRF/custom header is mandatory
        assert send(candidate, "unapproved").status_code == 422
        assert send(candidate, "access", user_id=99999).status_code == 201
        first = candidate.get("/api/account/privacy-requests")
        assert first.status_code == 200
        payload = first.json()
        assert payload["automatic_fulfillment"] is False
        assert len(payload["requests"]) == 1
        key = payload["requests"][0]["request_key"]
        assert payload["requests"][0]["status"] == "received"
        assert "email" not in str(payload["requests"])
        second = send(candidate, "access")
        assert second.status_code == 201
        assert second.json()["request"]["request_key"] == key

        assert send(candidate, "deletion").status_code == 201
        assert candidate.get("/api/me").status_code == 200  # no automatic erasure
        assert employer.get("/api/account/privacy-requests").json()["requests"] == []
        assert candidate.get("/api/admin/privacy-requests").status_code == 403
        assert candidate.post(
            "/api/admin/privacy-requests/" + key + "/status",
            headers=XHR, json={"status":"in_review"},
        ).status_code == 403

    with database(app.state.db_path) as db:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(privacy_rights_requests)")]
        assert "user_id" in cols
        for forbidden in ["email", "ip", "user_agent", "note", "message", "free_text"]:
            assert forbidden not in cols
        rows = db.execute(
            "SELECT request_key,user_id,kind,status FROM privacy_rights_requests"
        ).fetchall()
        assert len(rows) == 2
        assert all(r["user_id"] == candidate_id for r in rows)


def test_admin_decisions_require_review_manual_response_and_audit(tmp_path):
    app = create_app(str(tmp_path / "rights.sqlite"))
    with TestClient(app) as candidate:
        register(candidate, "rights@example.invalid")
        first = send(candidate, "correction")
        key = first.json()["request"]["request_key"]
        with database(app.state.db_path) as db:
            new_admin = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,?,?)",
                ("private-admin@example.invalid", "test-hash", "admin", "Admin"),
            )
            admin_id = new_admin.lastrowid

        assert candidate.get("/api/admin/privacy-requests").status_code == 403
        app.dependency_overrides[active_user] = lambda: {"role": "admin", "id": admin_id}
        admin_queue = candidate.get("/api/admin/privacy-requests")
        assert admin_queue.status_code == 200
        assert admin_queue.json()["requests"][0]["email"] == "rights@example.invalid"
        assert candidate.get("/api/admin/privacy-requests?status=invalid").status_code == 422

        endpoint = f"/api/admin/privacy-requests/{key}/status"
        early = candidate.post(
            endpoint, headers=XHR,
            json={"status":"completed","closure_reason":"fulfilled","manual_response_confirmed":True}
        )
        assert early.status_code == 409  # review precedes closure

        review = candidate.post(endpoint, headers=XHR, json={"status":"in_review"})
        assert review.status_code == 200
        assert review.json()["request"]["status"] == "in_review"
        assert candidate.post(endpoint, headers=XHR, json={
            "status":"completed","closure_reason":"fulfilled",
        }).status_code == 409
        assert candidate.post(endpoint, headers=XHR, json={
            "status":"completed","closure_reason":"retention_required",
            "manual_response_confirmed":True,
        }).status_code == 409
        assert candidate.post(endpoint, headers=XHR, json={
            "status":"declined","closure_reason":"fulfilled",
            "manual_response_confirmed":True,
        }).status_code == 409

        closed = candidate.post(endpoint, headers=XHR, json={
            "status":"completed","closure_reason":"fulfilled",
            "manual_response_confirmed":True,
        })
        assert closed.status_code == 200
        assert closed.json()["automatic_fulfillment"] is False
        assert closed.json()["request"]["status"] == "completed"
        assert candidate.post(endpoint, headers=XHR, json={"status":"in_review"}).status_code == 409
        assert candidate.post(
            "/api/admin/privacy-requests/" + "x"*25 + "/status",
            headers=XHR, json={"status":"in_review"}
        ).status_code == 404
        app.dependency_overrides.clear()

        as_user = candidate.get("/api/account/privacy-requests").json()["requests"]
        assert as_user[0]["status"] == "completed"
        # Same type may be submitted anew after previous request closes.
        assert send(candidate, "correction").json()["request"]["request_key"] != key

    with database(app.state.db_path) as db:
        transitions = db.execute(
            "SELECT from_status,to_status,admin_user_id FROM privacy_rights_admin_actions"
        ).fetchall()
        assert [(r["from_status"], r["to_status"],r["admin_user_id"]) for r in transitions] == [
            ("received", "in_review", admin_id),
            ("in_review", "completed", admin_id),
        ]
        assert db.execute(
            "SELECT closure_reason FROM privacy_rights_requests WHERE request_key=?", (key,)
        ).fetchone()["closure_reason"] == "fulfilled"


def test_rights_ui_and_server_routes_stay_within_authenticated_account(tmp_path):
    app = create_app(str(tmp_path / "rights.sqlite"))
    with TestClient(app) as client:
        script = client.get("/static/app.js").text
        assert "privacy-rights-request-form" in script
        assert "admin-privacy-rights" in script
        assert "manual_response_confirmed: true" in script
        assert "не удаляет аккаунт автоматически" in script
        assert client.get("/api/admin/privacy-requests").status_code == 401
        assert client.get("/api/account/privacy-requests").status_code == 401
