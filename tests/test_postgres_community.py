"""Exercise additive community startup and the full workflow on real PostgreSQL.

The fixture provisions an isolated CI database; never set TEST_DATABASE_URL to
an existing or production database. Ordinary local pytest runs skip this file.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import re
from uuid import uuid4

import pytest

pytest.importorskip("psycopg")

from fastapi.testclient import TestClient

from app.community import COMMUNITY_DDL
from app.main import create_app
from app.pg_compat import postgres_database
from app.release02 import init_release02
from app.security import make_password_hash
from test_postgres_runtime import runtime_db  # noqa: F401 - shared isolated PG fixture


XHR = {"X-Requested-With": "OPYT50"}
PASSWORD = "CommunityPGSynthetic2026!"


def _checked(response, expected=(200, 201)):
    assert response.status_code in expected, response.text
    return response.json()


def _profile(client, name, version=0):
    return _checked(client.put("/api/community/profile", headers=XHR, json={
        "expected_version": version, "public_name": name,
        "headline": "Наставник производственной команды", "city": "Москва",
        "skills": "Наставничество, организация работы",
        "about": "Обучаю коллег и помогаю организовывать учебные проекты.",
        "goal": "mentoring",
    }))["profile"]


def _publish(client, admin, profile):
    submitted = _checked(client.post("/api/community/profile/submit", headers=XHR, json={
        "expected_version": profile["version"], "publish_consent": True,
    }))["profile"]
    return _checked(admin.patch(
        "/api/admin/community/profiles/" + profile["public_id"], headers=XHR,
        json={"expected_version": submitted["version"], "decision": "approve", "reason": ""},
    ))["profile"]


def test_community_additive_startup_and_consented_conversation_in_postgresql(runtime_db, monkeypatch):
    """Real SQL, locking, CAS and cursor ordering, through authenticated HTTP APIs."""
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "0")
    monkeypatch.setenv("OPYT50_SMTP_HOST", "")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "")
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "")

    # Simulate an existing pre-community deployment. Additive startup must
    # recreate only the new tables and preserve existing hiring records.
    tables = [re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", statement).group(1)
              for statement in COMMUNITY_DDL if statement.startswith("CREATE TABLE")]
    with postgres_database(runtime_db) as db:
        for table in reversed(tables):
            db.execute(f"DROP TABLE IF EXISTS {table}")
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    init_release02("unused-pg-community")
    init_release02("unused-pg-community")
    with postgres_database(runtime_db) as db:
        assert db.execute("SELECT COUNT(*) FROM candidate_profiles").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 1
        password_hash = make_password_hash(PASSWORD)
        db.execute("UPDATE users SET password_hash=?", (password_hash,))
        db.execute("INSERT INTO users(id,email,password_hash,role,name,phone) VALUES(3,?,?,'candidate',?,?)",
                   ("community-other@example.invalid", password_hash, "Закрытое имя второго участника", "+70000000999"))
        db.execute("INSERT INTO candidate_profiles(user_id,profession) VALUES(3,'Приватное резюме')")
        db.execute("INSERT INTO users(id,email,password_hash,role,name) VALUES(4,?,?,'admin','Администратор')",
                   ("community-admin@example.invalid", password_hash))

    app = create_app("unused-pg-community")
    with ExitStack() as stack:
        # DATABASE_URL deliberately enables production-style Secure cookies.
        # Use an HTTPS test origin so the client sends them back unchanged.
        candidate, other, employer, admin, visitor = [
            stack.enter_context(TestClient(app, base_url="https://testserver")) for _ in range(5)
        ]
        for client, email in (
            (candidate, "c@example.invalid"), (other, "community-other@example.invalid"),
            (employer, "e@example.invalid"), (admin, "community-admin@example.invalid"),
        ):
            _checked(client.post("/api/login", headers=XHR, json={"email": email, "password": PASSWORD}))
            _checked(client.get("/api/me"))

        assert _checked(visitor.get("/api/community/people"))["total"] == 0
        own = _checked(candidate.get("/api/community/profile"))["profile"]
        assert own["version"] == 0 and own["public_name"] == ""
        one = _profile(candidate, "Учебный наставник")
        assert visitor.get("/api/community/people/" + one["public_id"]).status_code == 404
        one = _publish(candidate, admin, one)
        two = _publish(other, admin, _profile(other, "Учебный специалист"))
        listing = _checked(visitor.get("/api/community/people", params={"q": "НАСТАВНИК", "city": "МОСКВА"}))
        assert listing["total"] >= 1
        assert all(person["city"] == "Москва" for person in listing["people"])
        assert all("user_id" not in person and "email" not in person and "phone" not in person for person in listing["people"])

        # Opposite-direction simultaneous attempts serialize to the same pair.
        def request(client, public_id):
            return client.post("/api/community/connections", headers=XHR, json={
                "public_id": public_id, "purpose": "mentoring", "note": "Обсудим обучение коллег",
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request, candidate, two["public_id"])
            second = pool.submit(request, other, one["public_id"])
            rows = [_checked(first.result())["connection"], _checked(second.result())["connection"]]
        assert rows[0]["id"] == rows[1]["id"]
        connection_id = rows[0]["id"]
        sender, recipient = (candidate, other) if rows[0]["direction"] == "outgoing" else (other, candidate)
        assert employer.get("/api/community/connections/" + connection_id).status_code in (403, 404)
        assert sender.post("/api/community/connections/" + connection_id + "/respond", headers=XHR,
                           json={"decision": "accept"}).status_code == 403
        accepted = _checked(recipient.post(
            "/api/community/connections/" + connection_id + "/respond", headers=XHR, json={"decision": "accept"},
        ))["connection"]
        assert accepted["status"] == "accepted" and accepted["can_message"]
        key = str(uuid4())

        def send():
            return sender.post("/api/community/connections/" + connection_id + "/messages", headers=XHR,
                               json={"body": "Предлагаю составить учебный план", "client_key": key})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(send) for _ in range(2)]
            messages = [_checked(result.result())["message"] for result in results]
        assert messages[0]["id"] == messages[1]["id"]
        history = _checked(recipient.get("/api/community/connections/" + connection_id + "/messages"))
        assert len(history["messages"]) == 1
        assert history["messages"][0]["mine"] is False

        # Exercise the real PostgreSQL cursor comparison with a full history;
        # direct fixture inserts avoid overriding the actual anti-spam limit.
        with postgres_database(runtime_db) as db:
            sender_id = db.execute("SELECT sender_id FROM community_connections WHERE id=?", (connection_id,)).fetchone()[0]
            for index in range(60):
                db.execute("INSERT INTO community_messages(id,connection_id,sender_id,client_key,body,created_at) VALUES(?,?,?,?,?,?)",
                           (uuid4().hex, connection_id, sender_id, str(uuid4()), f"Учебное сообщение {index}",
                            f"2026-01-01T12:00:{index:02d}.000000+00:00"))
        newest = _checked(recipient.get("/api/community/connections/" + connection_id + "/messages"))
        assert len(newest["messages"]) == 50 and newest["has_more"] is True
        older = _checked(recipient.get("/api/community/connections/" + connection_id + "/messages",
                                       params={"before": newest["next_before"]}))
        all_ids = [item["id"] for item in older["messages"] + newest["messages"]]
        assert len(all_ids) == len(set(all_ids)) == 61
        assert older["has_more"] is False

        blocked = _checked(recipient.post("/api/community/connections/" + connection_id + "/block", headers=XHR))["connection"]
        assert blocked["status"] == "blocked" and not blocked["can_message"]
        assert sender.post("/api/community/connections/" + connection_id + "/messages", headers=XHR,
                           json={"body": "Запрещённое сообщение после блока", "client_key": str(uuid4())}).status_code in (403, 409)
        hidden = _checked(candidate.request("DELETE", "/api/community/profile/publication", headers=XHR,
                                            json={"expected_version": one["version"]}))["profile"]
        assert hidden["status"] == "hidden" and not hidden["consent_at"]
        assert visitor.get("/api/community/people/" + one["public_id"]).status_code == 404
        assert candidate.post("/api/community/profile/submit", headers=XHR,
                              json={"expected_version": one["version"], "publish_consent": True}).status_code == 409
        assert admin.patch("/api/admin/community/profiles/" + one["public_id"], headers=XHR,
                           json={"expected_version": one["version"], "decision": "approve", "reason": ""}).status_code == 409
        with postgres_database(runtime_db) as db:
            assert db.execute("SELECT COUNT(*) FROM community_connections").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0

