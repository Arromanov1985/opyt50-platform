"""Deletion/cessation dry-run and human disposition gates.

Every test uses fictional data; not a production erasure implementation.
"""
import json

from fastapi.testclient import TestClient
from app.db import database
from app.main import active_user, create_app
from app.privacy_disposal import CHECKS, impact_preview, review_state

XHR = {"X-Requested-With": "OPYT50"}


def signup(client, role, email):
    data = {
        "role": role, "name": "Тестовый участник",
        "email": email, "password": "SuperSecureTestPassword2026!",
    }
    if role == "employer":
        data["company_name"] = "Учебная компания"
    response = client.post("/api/register", headers=XHR, json=data)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def test_impact_preview_is_read_only_and_excludes_other_peoples_details(tmp_path):
    app = create_app(str(tmp_path / "dry-run.sqlite"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        cid = signup(candidate, "candidate", "testcandidate@example.invalid")
        eid = signup(employer, "employer", "employer-secret@example.invalid")
        with database(app.state.db_path) as db:
            vacancy = db.execute(
                """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,skills)
                   VALUES(?,?,?,?,?,?)""",
                (eid, "Кандидат для вакансии", "Москва", 50000, 100000, "Работа"),
            ).lastrowid
            db.execute("INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)",
                       (vacancy, cid))
            db.execute(
                """INSERT INTO invitations
                   (vacancy_id,candidate_id,employer_id,status,share_consent,contact_shared,price_rub)
                   VALUES(?,?,?,'accepted',1,1,0)""", (vacancy, cid, eid),
            )
        rights = candidate.post("/api/account/privacy-requests", headers=XHR,
                                json={"kind": "deletion"})
        assert rights.status_code == 201
        key = rights.json()["request"]["request_key"]
        assert candidate.get("/api/admin/privacy-requests/" + key + "/impact").status_code == 403

        with database(app.state.db_path) as db:
            before = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            preview = impact_preview(db, key)
            assert preview["read_only"] is True
            assert preview["automatic_deletion"] is False
            assert preview["counts"]["applications"] == 1
            assert preview["counts"]["contacts_already_shared"] == 1
            assert "employer-secret@example.invalid" not in json.dumps(preview)
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == before
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 1


def test_admin_preflight_and_checkpoint_gate_fulfillment(tmp_path):
    app = create_app(str(tmp_path / "review.sqlite"))
    with TestClient(app) as client:
        cid = signup(client, "candidate", "review-candidate@example.invalid")
        key = client.post("/api/account/privacy-requests", headers=XHR,
                          json={"kind":"stop_processing"}).json()["request"]["request_key"]
        with database(app.state.db_path) as db:
            admin_id = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,?,?)",
                ("test-admin@example.invalid", "testing", "admin", "Администратор"),
            ).lastrowid
        preview_url = f"/api/admin/privacy-requests/{key}/impact"
        checklist_url = f"/api/admin/privacy-requests/{key}/disposition-review"
        status_url = f"/api/admin/privacy-requests/{key}/status"
        assert client.get(preview_url).status_code == 403
        assert client.post(checklist_url, headers=XHR, json={k:True for k in CHECKS}).status_code == 403

        app.dependency_overrides[active_user] = lambda: {"id": admin_id, "role": "admin"}
        assert client.get(preview_url).status_code == 200
        preview = client.get(preview_url).json()["preview"]
        assert preview["account_role"] == "candidate"
        assert preview["kind"] == "stop_processing"
        assert "email" not in json.dumps(preview)

        assert client.get(checklist_url).json()["review"]["ready_for_manual_closure"] is False
        # Checklist cannot be signed before the request is accepted for review.
        response = client.post(checklist_url, headers=XHR, json={k:True for k in CHECKS})
        assert response.status_code == 409

        assert client.post(status_url, headers=XHR, json={"status":"in_review"}).status_code == 200
        final = {"status":"completed", "manual_response_confirmed":True,
                 "closure_reason":"fulfilled"}
        assert client.post(status_url, headers=XHR, json=final).status_code == 409

        partial = {k:(k != "manual_action_verified") for k in CHECKS}
        assert client.post(checklist_url, json=partial).status_code == 403
        bad = client.post(checklist_url, headers=XHR, json={
            **partial, "identity_reviewed": "yes"
        })
        assert bad.status_code == 422
        saved = client.post(checklist_url, headers=XHR, json=partial)
        assert saved.status_code == 200, saved.text
        assert saved.json()["review"]["ready_for_manual_closure"] is False
        assert saved.json()["actual_deletion_performed"] is False
        assert client.post(status_url, headers=XHR, json=final).status_code == 409

        checked = {k:True for k in CHECKS}
        saved = client.post(checklist_url, headers=XHR, json=checked)
        assert saved.status_code == 200
        assert saved.json()["review"]["ready_for_manual_closure"] is True
        closed = client.post(status_url, headers=XHR, json=final)
        assert closed.status_code == 200
        assert closed.json()["automatic_fulfillment"] is False
        app.dependency_overrides.clear()
        # Important: a clerical attestation DOES NOT erase or disable a profile.
        assert client.get("/api/me").status_code == 200
        assert client.get("/api/account/privacy-requests").json()["requests"][0]["status"] == "completed"
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM users WHERE id=?", (cid,)).fetchone()[0] == 1
            trail = db.execute(
                "SELECT checks_bits FROM privacy_disposal_review_actions WHERE request_key=?",
                (key,),
            ).fetchall()
            assert [r["checks_bits"] for r in trail] == ["1111110", "1111111"]
            assert review_state(db, key)["ready_for_manual_closure"] is True


def test_preflight_is_admin_only_and_rejects_non_disposal_requests(tmp_path):
    app = create_app(str(tmp_path / "other-kind.sqlite"))
    with TestClient(app) as client, TestClient(app) as guest:
        signup(client, "candidate", "notdeleting@example.invalid")
        key = client.post("/api/account/privacy-requests", headers=XHR,
                          json={"kind":"access"}).json()["request"]["request_key"]
        assert guest.get(f"/api/admin/privacy-requests/{key}/impact").status_code == 401
        with database(app.state.db_path) as db:
            admin_id = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,?,?)",
                ("other-admin@example.invalid","test-hash","admin","Admin"),
            ).lastrowid
        app.dependency_overrides[active_user] = lambda: {"id":admin_id,"role":"admin"}
        assert client.get(f"/api/admin/privacy-requests/{key}/impact").status_code == 409
        assert client.get(f"/api/admin/privacy-requests/{key}/disposition-review").status_code == 409
        assert client.get("/api/admin/privacy-requests/not-here/impact").status_code == 422
        assert client.get("/api/admin/privacy-requests/this-is-a-valid-key-123/impact").status_code == 404
        app.dependency_overrides.clear()


def test_employer_impact_counts_third_party_application_risk(tmp_path):
    app = create_app(str(tmp_path / "employer-impact.sqlite"))
    with TestClient(app) as employer, TestClient(app) as candidate:
        eid = signup(employer, "employer", "employer@example.invalid")
        cid = signup(candidate, "candidate", "candidate@example.invalid")
        with database(app.state.db_path) as db:
            vid = db.execute(
                """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,skills)
                   VALUES(?,?,?,?,?,?)""",
                (eid, "Работа", "Москва", 45000, 90000, "Опыт"),
            ).lastrowid
            db.execute(
                "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)",
                (vid,cid),
            )
        key = employer.post("/api/account/privacy-requests",headers=XHR,
                            json={"kind":"deletion"}).json()["request"]["request_key"]
        with database(app.state.db_path) as db:
            preview=impact_preview(db,key)
        assert preview["counts"]["open_vacancies"] == 1
        assert preview["counts"]["candidate_applications_affected"] == 1
        assert any("третьих лиц" in note for note in preview["risk_flags"])
        assert preview["automatic_deletion"] is False
