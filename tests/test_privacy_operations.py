"""Legal retention registry and external-provider reviews are fail-closed."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import active_user, create_app
from app.retention_register import retention_readiness, REQUIRED
from app.privacy_external import SYSTEMS

XHR = {"X-Requested-With": "OPYT50"}


def create_candidate(client):
    r=client.post("/api/register", headers=XHR, json={
        "email":"subject@example.invalid", "name":"Тестовый заявитель",
        "role":"candidate", "password":"StrongTestPassword2026!!"
    })
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"]


def test_retention_matrix_is_explicitly_unapproved_and_no_automatic_purge():
    report = retention_readiness()
    assert report["approved"] is False
    assert report["status"] == "TEST_ONLY"
    assert report["total"] == 16
    assert report["approved_count"] == 0
    assert report["automatic_purge_enabled"] is False
    assert len(report["categories"]) == len(REQUIRED)
    assert all(not x["period_defined"] for x in report["categories"])
    assert len(report["blockers"]) >= len(REQUIRED)


def test_registry_rejects_missing_categories_and_unverified_authority(tmp_path:Path):
    from app.retention_register import REGISTER
    doc = json.loads(REGISTER.read_text(encoding="utf-8"))
    doc["status"] = "APPROVED"
    doc["effective_date"] = "2026-11-19"
    doc["categories"].pop()
    out = tmp_path / "incomplete.json"
    out.write_text(json.dumps(doc,ensure_ascii=False),encoding="utf-8")
    report = retention_readiness(out)
    assert not report["approved"]
    assert any("missing categories:" in error for error in report["blockers"])
    assert all(not c["period_defined"] for c in report["categories"])


def test_external_provider_review_requires_admin_and_manual_state(tmp_path):
    app=create_app(str(tmp_path / "external.db"))
    with TestClient(app) as owner, TestClient(app) as anonymous:
        uid=create_candidate(owner)
        key=owner.post(
            "/api/account/privacy-requests", headers=XHR,
            json={"kind":"deletion"}
        ).json()["request"]["request_key"]
        prefix=f"/api/admin/privacy-requests/{key}/external-review"
        assert anonymous.get(prefix).status_code == 401
        assert owner.get(prefix).status_code == 403
        assert owner.get("/api/admin/privacy-retention-readiness").status_code == 403
        assert owner.post(
            prefix+"/database_backups",headers=XHR,json={"status":"reviewed"}
        ).status_code == 403

        with database(app.state.db_path) as db:
            admin_id=db.execute(
                "INSERT INTO users(email,role,name,password_hash) VALUES(?,?,?,?)",
                ("adminreview@example.invalid","admin","Admin","testhash")
            ).lastrowid

        app.dependency_overrides[active_user]=lambda:{"id":admin_id,"role":"admin"}
        readiness=owner.get("/api/admin/privacy-retention-readiness")
        assert readiness.status_code == 200
        assert readiness.json()["approved"] is False
        assert "subject@example.invalid" not in readiness.text

        response=owner.get(prefix)
        assert response.status_code == 200
        assert response.json()["review"]["ready_for_manual_closure"] is False
        assert len(response.json()["review"]["checks"]) == len(SYSTEMS)
        assert owner.post(prefix+"/database_backups",headers=XHR,json={
            "status":"reviewed"}).status_code == 409
        status=f"/api/admin/privacy-requests/{key}/status"
        assert owner.post(status,headers=XHR,json={"status":"in_review"}).status_code == 200
        assert owner.post(prefix+"/not_real",headers=XHR,json={
            "status":"reviewed"}).status_code == 409
        assert owner.post(prefix+"/database_backups",headers=XHR,json={
            "status":"unverified"}).status_code == 422
        assert owner.post(prefix+"/database_backups",json={
            "status":"reviewed"}).status_code == 403

        for system_key,_ in SYSTEMS:
            response=owner.post(prefix+"/"+system_key,headers=XHR,json={
                "status":"reviewed" if system_key!="third_party_recipients"
                    else "followup_required"
            })
            assert response.status_code == 200,response.text
            assert response.json()["external_action_performed"] is False

        report=owner.get(prefix).json()["review"]
        assert report["ready_for_manual_closure"] is False
        response=owner.post(prefix+"/third_party_recipients",headers=XHR,json={
            "status":"not_applicable"
        })
        assert response.status_code == 200
        assert response.json()["review"]["ready_for_manual_closure"] is True
        app.dependency_overrides.clear()

        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM users WHERE id=?", (uid,)
            ).fetchone()[0] == 1
            count=db.execute(
                "SELECT COUNT(*) FROM privacy_external_review_events WHERE request_key=?",
                (key,),
            ).fetchone()[0]
            assert count == len(SYSTEMS)+1


def test_external_system_review_rejects_access_request(tmp_path):
    app=create_app(str(tmp_path / "external-other.db"))
    with TestClient(app) as client:
        create_candidate(client)
        key=client.post(
            "/api/account/privacy-requests",headers=XHR,json={"kind":"access"}
        ).json()["request"]["request_key"]
        with database(app.state.db_path) as db:
            aid=db.execute(
                "INSERT INTO users(email,role,name,password_hash) VALUES(?,?,?,?)",
                ("admin-other@example.invalid","admin","Admin","testhash")
            ).lastrowid
        app.dependency_overrides[active_user]=lambda:{"id":aid,"role":"admin"}
        assert client.get(
            f"/api/admin/privacy-requests/{key}/external-review"
        ).status_code == 409
        assert client.post(
            f"/api/admin/privacy-requests/{key}/external-review/database_backups",
            headers=XHR,json={"status":"reviewed"}
        ).status_code == 409
        app.dependency_overrides.clear()
