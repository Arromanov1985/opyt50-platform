"""Professional community: opt-in, moderation, isolation and durable consent."""
from contextlib import ExitStack
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.community import COMMUNITY_DDL, CONSENT_VERSION, PUBLIC_FIELDS
from app.db import database
from app.main import create_app
from app.security import make_password_hash


HEADERS = {"X-Requested-With": "OPYT50"}
PASSWORD = "Community test password 2026!"
PROFILE = {
    "public_name": "Коллега с опытом",
    "headline": "Наставник по работе со складом",
    "city": "Подольск",
    "skills": "Управление складом, обучение команды",
    "about": "Помогаю коллегам выстроить понятные процессы и освоить работу со складом.",
    "goal": "mentoring",
}


def mutate(client, method, path, body=None):
    return client.request(method, path, headers=HEADERS, json={} if body is None else body)


def register(client, email, role="candidate"):
    data = {"role": role, "name": "Закрытое имя владельца", "email": email,
            "phone": "+79991234567", "password": PASSWORD}
    if role == "employer":
        data["company_name"] = "Учебная компания"
    result = mutate(client, "POST", "/api/register", data)
    assert result.status_code == 201, result.text
    return result.json()["user"]["id"]


@pytest.fixture
def community(tmp_path):
    app = create_app(str(tmp_path / "community.db"))
    with ExitStack() as stack:
        clients = {key: stack.enter_context(TestClient(app)) for key in
                   ("first", "second", "outsider", "employer", "admin", "visitor")}
        ids = {key: register(clients[key], key + "@community.example.invalid",
                             "employer" if key == "employer" else "candidate")
               for key in ("first", "second", "outsider", "employer")}
        with database(app.state.db_path) as db:
            db.execute("INSERT INTO users(role,email,name,password_hash) VALUES('admin',?,?,?)",
                       ("moderator@community.example.invalid", "Модератор", make_password_hash(PASSWORD)))
        login = mutate(clients["admin"], "POST", "/api/login",
                       {"email": "moderator@community.example.invalid", "password": PASSWORD})
        assert login.status_code == 200, login.text
        yield app, clients, ids


def save(client, **changes):
    current = client.get("/api/community/profile").json()["profile"]
    fields = {key: current[key] for key in PROFILE}
    fields.update(changes or PROFILE)
    response = mutate(client, "PUT", "/api/community/profile",
                      {**fields, "expected_version": current["version"]})
    assert response.status_code == 200, response.text
    return response.json()["profile"]


def submit(client, profile=None):
    profile = profile or client.get("/api/community/profile").json()["profile"]
    response = mutate(client, "POST", "/api/community/profile/submit",
                      {"expected_version": profile["version"], "publish_consent": True})
    assert response.status_code == 200, response.text
    return response.json()["profile"]


def approve(admin, profile):
    response = mutate(admin, "PATCH", "/api/admin/community/profiles/" + profile["public_id"],
                      {"expected_version": profile["version"], "decision": "approve"})
    assert response.status_code == 200, response.text
    return response.json()["profile"]


def publish(clients, key="first", **changes):
    profile = save(clients[key], **({**PROFILE, **changes}))
    return approve(clients["admin"], submit(clients[key], profile))


def connect(clients, public_id, sender="first"):
    response = mutate(clients[sender], "POST", "/api/community/connections",
                      {"public_id": public_id, "purpose": "mentoring", "note": "Хотел бы обсудить рабочий проект."})
    assert response.status_code == 200, response.text
    return response.json()["connection"]


def test_profiles_are_separate_private_by_default_and_get_is_read_only(community):
    app, clients, ids = community
    first, visitor = clients["first"], clients["visitor"]
    with database(app.state.db_path) as db:
        db.execute("UPDATE candidate_profiles SET profession='Частное резюме',about='Приватное описание' WHERE user_id=?",
                   (ids["first"],))
    blank = first.get("/api/community/profile")
    assert blank.status_code == 200
    assert blank.json()["profile"]["version"] == 0
    assert blank.json()["profile"]["public_id"] is None
    assert blank.json()["profile"]["about"] == ""
    assert visitor.get("/api/community/people").json()["people"] == []
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_profiles").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM community_actor_locks").fetchone()[0] == 0
    assert visitor.get("/api/community/profile").status_code == 401
    assert clients["employer"].get("/api/community/profile").status_code == 403
    assert clients["outsider"].get("/api/admin/community/profiles").status_code == 403
    assert first.put("/api/community/profile", json={**PROFILE, "expected_version": 0}).status_code == 403
    draft = save(first)
    assert draft["status"] == "draft"
    assert draft["consent_at"] is None
    assert visitor.get("/api/community/people/" + draft["public_id"]).status_code == 404


def test_publication_requires_separate_consent_and_current_moderator_approval(community):
    app, clients, ids = community
    first, admin, visitor = clients["first"], clients["admin"], clients["visitor"]
    profile = save(first)
    denied = mutate(first, "POST", "/api/community/profile/submit", {"expected_version": profile["version"]})
    assert denied.status_code == 400
    # Strings must not stand in for explicit checkbox consent.
    assert mutate(first, "POST", "/api/community/profile/submit", {
        "expected_version": profile["version"], "publish_consent": "true",
    }).status_code == 422
    assert mutate(admin, "PATCH", "/api/admin/community/profiles/" + profile["public_id"], {
        "expected_version": profile["version"], "decision": "approve",
    }).status_code == 409
    pending = submit(first, profile)
    assert pending["status"] == "pending" and pending["consent_at"]
    assert pending["consent_version"] == CONSENT_VERSION
    assert visitor.get("/api/community/people").json()["total"] == 0
    listed = admin.get("/api/admin/community/profiles").json()
    assert listed["profiles"][0]["public_id"] == profile["public_id"]
    approved = approve(admin, pending)
    public = visitor.get("/api/community/people/" + profile["public_id"])
    assert public.status_code == 200 and public.headers["cache-control"] == "no-store"
    assert set(public.json()["person"]) == set(PUBLIC_FIELDS)
    assert visitor.get("/api/community/people?q=НАСТАВНИК&city=ПОДОЛЬСК&goal=mentoring").json()["total"] == 1
    assert visitor.get("/api/community/people?q=бухгалтер").json()["people"] == []
    assert visitor.get("/api/community/people?page=0").status_code == 422
    for private in ("Закрытое имя", "+79991234567", "first@community", "user_id", "consent_at", "version"):
        assert private not in public.text
    # Re-saving identical content must not accidentally withdraw a published page.
    unchanged = mutate(first, "PUT", "/api/community/profile", {**PROFILE, "expected_version": approved["version"]})
    assert unchanged.json()["profile"] == approved
    with database(app.state.db_path) as db:
        events = db.execute("SELECT event FROM community_profile_events WHERE user_id=? ORDER BY created_at", (ids["first"],)).fetchall()
    assert [row[0] for row in events] == ["saved", "submitted_with_consent", "moderator_approve"]


def test_withdrawal_and_edits_invalidate_consent_and_stale_tabs(community):
    _, clients, _ = community
    first, admin, visitor = clients["first"], clients["admin"], clients["visitor"]
    original = publish(clients)
    withdrawn = mutate(first, "DELETE", "/api/community/profile/publication",
                       {"expected_version": original["version"]})
    assert withdrawn.status_code == 200
    hidden = withdrawn.json()["profile"]
    assert hidden["status"] == "hidden" and hidden["consent_at"] is None
    assert visitor.get("/api/community/people/" + original["public_id"]).status_code == 404
    assert visitor.get("/api/community/people").json()["total"] == 0
    assert mutate(first, "POST", "/api/community/profile/submit", {
        "expected_version": original["version"], "publish_consent": True,
    }).status_code == 409
    assert mutate(first, "PUT", "/api/community/profile", {**PROFILE, "expected_version": original["version"]}).status_code == 409
    pending = submit(first, hidden)
    changed = save(first, about="Измененная профессиональная информация для проверки новой редакции.")
    assert changed["status"] == "draft" and changed["consent_at"] is None
    assert mutate(admin, "PATCH", "/api/admin/community/profiles/" + pending["public_id"], {
        "decision": "approve", "expected_version": pending["version"],
    }).status_code == 409
    assert mutate(admin, "PATCH", "/api/admin/community/profiles/" + changed["public_id"], {
        "decision": "approve", "expected_version": changed["version"],
    }).status_code == 409
    # Even a currently pending version disappears immediately on withdrawal.
    pending = submit(first, changed)
    assert mutate(first, "DELETE", "/api/community/profile/publication", {"expected_version": pending["version"]}).status_code == 200
    assert mutate(admin, "PATCH", "/api/admin/community/profiles/" + pending["public_id"], {
        "decision": "approve", "expected_version": pending["version"],
    }).status_code == 409


def test_unsent_drafts_are_not_exposed_to_moderation_even_after_withdrawal(community):
    _, clients, _ = community
    owner, admin = clients["first"], clients["admin"]
    draft = save(owner, **{**PROFILE, "about": "Мой приватный черновик, еще не отправленный модератору."})
    assert admin.get("/api/admin/community/profiles?status=draft").status_code == 422
    assert mutate(admin, "PATCH", "/api/admin/community/profiles/" + draft["public_id"], {
        "decision": "hide", "expected_version": draft["version"], "reason": "Проверка",
    }).status_code == 409
    hidden = mutate(owner, "DELETE", "/api/community/profile/publication", {"expected_version": draft["version"]}).json()["profile"]
    assert admin.get("/api/admin/community/profiles?status=hidden").json()["profiles"] == []
    submitted = submit(owner, hidden)
    published = approve(admin, submitted)
    assert admin.get("/api/admin/community/profiles?status=published").json()["total"] == 1
    new_draft = save(owner, about="Новая несогласованная редакция: опыт работы с 2010-2026.")
    assert mutate(admin, "PATCH", "/api/admin/community/profiles/" + published["public_id"], {
        "decision": "hide", "expected_version": new_draft["version"], "reason": "Проверка",
    }).status_code == 409
    mutate(owner, "DELETE", "/api/community/profile/publication", {"expected_version": new_draft["version"]})
    assert admin.get("/api/admin/community/profiles?status=hidden").json()["profiles"] == []


@pytest.mark.parametrize("field,value", [
    ("public_name", "author@example.invalid"),
    ("headline", "Напишите name @ example.invalid"),
    ("about", "Звоните +7 (999) 123-45-67 для обсуждения проекта."),
    ("skills", "https://example.invalid"),
    ("city", "@telegram_user"),
    ("about", "Портфолио example.ru обо мне и рабочем опыте"),
])
def test_public_text_rejects_contacts_and_links(community, field, value):
    _, clients, _ = community
    response = mutate(clients["first"], "PUT", "/api/community/profile",
                      {**PROFILE, field: value, "expected_version": 0})
    assert response.status_code == 422
    assert clients["first"].get("/api/community/profile").json()["profile"]["version"] == 0


def test_moderator_rejection_hiding_and_disabled_accounts_are_not_public(community):
    app, clients, ids = community
    pending = submit(clients["first"], save(clients["first"]))
    path = "/api/admin/community/profiles/" + pending["public_id"]
    assert mutate(clients["admin"], "PATCH", path, {"decision": "reject", "expected_version": pending["version"]}).status_code == 422
    rejected = mutate(clients["admin"], "PATCH", path, {
        "decision": "reject", "expected_version": pending["version"], "reason": "Уточните профессиональный опыт",
    }).json()["profile"]
    assert rejected["status"] == "rejected" and rejected["consent_at"] is None
    assert "Уточните" in rejected["moderation_reason"]
    approved = approve(clients["admin"], submit(clients["first"], rejected))
    with database(app.state.db_path) as db:
        db.execute("INSERT INTO account_controls(user_id,status) VALUES(?,'disabled') ON CONFLICT(user_id) DO UPDATE SET status='disabled'",
                   (ids["first"],))
    assert clients["visitor"].get("/api/community/people/" + approved["public_id"]).status_code == 404
    assert clients["visitor"].get("/api/community/people").json()["total"] == 0
    assert clients["first"].get("/api/community/profile").status_code == 403
    with database(app.state.db_path) as db:
        db.execute("UPDATE account_controls SET status='active' WHERE user_id=?", (ids["first"],))
    hidden = mutate(clients["admin"], "PATCH", path, {
        "decision": "hide", "expected_version": approved["version"], "reason": "Проверка жалобы",
    })
    assert hidden.status_code == 200 and hidden.json()["profile"]["status"] == "hidden"
    assert clients["visitor"].get("/api/community/people/" + approved["public_id"]).status_code == 404


def test_connections_require_opt_in_identity_and_never_auto_accept_reciprocal_requests(community):
    app, clients, ids = community
    second = publish(clients, "second", public_name="Второй коллега")
    request = {"public_id": second["public_id"], "purpose": "exchange"}
    assert mutate(clients["first"], "POST", "/api/community/connections", request).status_code == 403
    first = publish(clients)
    assert mutate(clients["first"], "POST", "/api/community/connections", {
        **request, "note": "Мой телефон +79991234567",
    }).status_code == 422
    assert mutate(clients["second"], "POST", "/api/community/connections", request).status_code == 400
    assert mutate(clients["admin"], "POST", "/api/community/connections", request).status_code == 403
    created = connect(clients, second["public_id"])
    assert created["direction"] == "outgoing" and created["status"] == "pending"
    assert created["can_cancel"] and not created["can_respond"] and not created["can_message"]
    assert connect(clients, second["public_id"])["id"] == created["id"]
    reciprocal = connect(clients, first["public_id"], sender="second")
    assert reciprocal["id"] == created["id"] and reciprocal["status"] == "pending"
    assert reciprocal["direction"] == "incoming" and reciprocal["can_respond"]
    path = "/api/community/connections/" + created["id"]
    assert clients["outsider"].get(path).status_code == 404
    assert clients["admin"].get(path).status_code == 404
    assert mutate(clients["first"], "POST", path + "/respond", {"decision": "accept"}).status_code == 403
    assert clients["second"].get(path + "/messages").status_code == 403
    assert mutate(clients["second"], "POST", path + "/messages", {"body": "До согласия", "client_key": str(uuid4())}).status_code == 403
    for client in (clients["first"], clients["second"]):
        raw = client.get("/api/community/connections").text
        for private in ("Закрытое имя", "+79991234567", "@community.example", "sender_id", "recipient_id"):
            assert private not in raw
    employer = connect(clients, second["public_id"], sender="employer")
    incoming = clients["second"].get("/api/community/connections/" + employer["id"]).json()["connection"]
    assert incoming["counterpart"]["public_name"] == "Учебная компания"
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM community_connections WHERE pair_low=? AND pair_high=?",
                          tuple(sorted((ids["first"], ids["second"])))).fetchone()[0] == 1


def test_private_chat_idempotency_history_withdrawal_and_blocking(community):
    app, clients, ids = community
    first = publish(clients)
    second = publish(clients, "second", public_name="Второй коллега")
    connection = connect(clients, second["public_id"])
    path = "/api/community/connections/" + connection["id"]
    accepted = mutate(clients["second"], "POST", path + "/respond", {"decision": "accept"})
    assert accepted.status_code == 200 and accepted.json()["connection"]["can_message"]
    assert mutate(clients["second"], "POST", path + "/respond", {"decision": "accept"}).status_code == 200
    assert mutate(clients["second"], "POST", path + "/respond", {"decision": "decline"}).status_code == 409
    token = str(uuid4())
    payload = {"body": "Как организовать наставничество в команде? <script>alert(1)</script>", "client_key": token}
    original = mutate(clients["first"], "POST", path + "/messages", payload)
    assert original.status_code == 200, original.text
    duplicate = mutate(clients["first"], "POST", path + "/messages", payload)
    assert original.json() == duplicate.json()
    assert mutate(clients["first"], "POST", path + "/messages", {**payload, "body": "Другое сообщение"}).status_code == 409
    assert mutate(clients["outsider"], "POST", path + "/messages", payload).status_code == 404
    assert clients["outsider"].get(path + "/messages").status_code == 404
    history = clients["second"].get(path + "/messages").json()
    assert len(history["messages"]) == 1 and history["messages"][0]["mine"] is False
    assert set(history["messages"][0]) == {"id", "body", "mine", "created_at"}
    # Several equal timestamps retain a stable cursor/tie-break order.
    with database(app.state.db_path) as db:
        for index in range(55):
            db.execute("INSERT INTO community_messages(id,connection_id,sender_id,client_key,body,created_at) VALUES(?,?,?,?,?,?)",
                       (f"seed-{index:03}", connection["id"], ids["first"], str(uuid4()), f"История {index}", "2026-01-01T12:00:00.000000+00:00"))
    newest = clients["first"].get(path + "/messages").json()
    older = clients["first"].get(path + "/messages", params={"before": newest["next_before"]}).json()
    assert len(newest["messages"]) == 50 and newest["has_more"]
    assert len(older["messages"]) == 6 and not older["has_more"]
    assert len({item["id"] for item in newest["messages"] + older["messages"]}) == 56
    assert clients["first"].get(path + "/messages?before=unknown").status_code == 400
    assert mutate(clients["first"], "DELETE", "/api/community/profile/publication", {"expected_version": first["version"]}).status_code == 200
    counterpart = clients["second"].get(path).json()["connection"]["counterpart"]
    assert counterpart["public_name"] == "Участник СТАЖНО" and counterpart["public_id"] is None
    # Withdrawing the public page does not silently destroy a mutually accepted private conversation.
    assert mutate(clients["first"], "POST", path + "/messages", {"body": "Продолжим здесь", "client_key": str(uuid4())}).status_code == 200
    blocked = mutate(clients["second"], "POST", path + "/block")
    assert blocked.status_code == 200 and blocked.json()["connection"]["status"] == "blocked"
    assert not blocked.json()["connection"]["can_message"]
    for key in ("first", "second"):
        assert mutate(clients[key], "POST", path + "/messages", {"body": "После блока", "client_key": str(uuid4())}).status_code == 403
        assert clients[key].get(path + "/messages").status_code == 200  # retained read-only history
    assert mutate(clients["first"], "POST", "/api/community/connections", {
        "public_id": second["public_id"], "purpose": "work",
    }).status_code == 409


@pytest.mark.parametrize("decision", ["decline", "cancel"])
def test_finished_requests_cannot_be_reopened_or_used_for_messages(community, decision):
    _, clients, _ = community
    publish(clients)
    second = publish(clients, "second")
    connection = connect(clients, second["public_id"])
    path = "/api/community/connections/" + connection["id"]
    if decision == "cancel":
        assert mutate(clients["second"], "POST", path + "/cancel").status_code == 403
        result = mutate(clients["first"], "POST", path + "/cancel")
    else:
        result = mutate(clients["second"], "POST", path + "/respond", {"decision": decision})
    assert result.status_code == 200
    assert mutate(clients["second"], "POST", path + "/respond", {"decision": "accept"}).status_code == 409
    assert clients["first"].get(path + "/messages").status_code == 403
    assert mutate(clients["first"], "POST", "/api/community/connections", {
        "public_id": second["public_id"], "purpose": "projects",
    }).status_code == 409


def test_disabled_peer_prevents_new_messages_and_acceptance(community):
    app, clients, ids = community
    publish(clients)
    second = publish(clients, "second")
    connection = connect(clients, second["public_id"])
    path = "/api/community/connections/" + connection["id"]
    with database(app.state.db_path) as db:
        db.execute("INSERT INTO account_controls(user_id,status) VALUES(?,'disabled') ON CONFLICT(user_id) DO UPDATE SET status='disabled'", (ids["first"],))
    assert mutate(clients["second"], "POST", path + "/respond", {"decision": "accept"}).status_code == 409
    assert clients["second"].get(path).json()["connection"]["counterpart"]["public_name"] == "Участник недоступен"
    with database(app.state.db_path) as db:
        db.execute("UPDATE account_controls SET status='active' WHERE user_id=?", (ids["first"],))
    assert mutate(clients["second"], "POST", path + "/respond", {"decision": "accept"}).status_code == 200
    with database(app.state.db_path) as db:
        db.execute("UPDATE account_controls SET status='disabled' WHERE user_id=?", (ids["first"],))
    assert not clients["second"].get(path).json()["connection"]["can_message"]
    assert mutate(clients["second"], "POST", path + "/messages", {"body": "Тест", "client_key": str(uuid4())}).status_code == 403
    # A user can still stop an unwanted/disabled peer's pending or accepted connection.
    assert mutate(clients["second"], "POST", path + "/block").status_code == 200


def test_reports_are_private_unique_and_reviewable(community):
    app, clients, _ = community
    first = publish(clients)
    second = publish(clients, "second")
    connection = connect(clients, second["public_id"])
    report_payload = {"public_id": first["public_id"], "reason": "personal_data", "details": "Проверьте опубликованный текст"}
    response = mutate(clients["outsider"], "POST", "/api/community/reports", report_payload)
    assert response.status_code == 200, response.text
    assert mutate(clients["outsider"], "POST", "/api/community/reports", report_payload).json() == response.json()
    report_id = response.json()["report"]["id"]
    assert mutate(clients["outsider"], "POST", "/api/community/reports", {
        "connection_id": connection["id"], "reason": "spam",
    }).status_code == 404
    assert mutate(clients["first"], "POST", "/api/community/reports", {
        "connection_id": connection["id"], "reason": "harassment",
    }).status_code == 200
    assert mutate(clients["first"], "POST", "/api/community/reports", {
        "public_id": first["public_id"], "connection_id": connection["id"], "reason": "spam",
    }).status_code == 422
    assert clients["first"].get("/api/admin/community/reports").status_code == 403
    admin_reports = clients["admin"].get("/api/admin/community/reports").json()
    assert admin_reports["total"] == 2
    assert all("reporter_id" not in item for item in admin_reports["reports"])
    reviewed = mutate(clients["admin"], "PATCH", "/api/admin/community/reports/" + report_id, {"status": "resolved"})
    assert reviewed.status_code == 200
    assert clients["admin"].get("/api/admin/community/reports?status=resolved").json()["total"] == 1
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_reports").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM security_events WHERE event_type='community_report_reviewed'").fetchone()[0] == 1


def test_message_rate_limit_is_persisted_and_retries_do_not_consume_it(community):
    app, clients, _ = community
    publish(clients)
    second = publish(clients, "second")
    connection = connect(clients, second["public_id"])
    path = "/api/community/connections/" + connection["id"]
    assert mutate(clients["second"], "POST", path + "/respond", {"decision": "accept"}).status_code == 200
    first_payload = {"body": "Первое сообщение", "client_key": str(uuid4())}
    assert mutate(clients["first"], "POST", path + "/messages", first_payload).status_code == 200
    for _ in range(4):
        assert mutate(clients["first"], "POST", path + "/messages", first_payload).status_code == 200
    for index in range(29):
        assert mutate(clients["first"], "POST", path + "/messages", {"body": f"Сообщение {index}", "client_key": str(uuid4())}).status_code == 200
    limited = mutate(clients["first"], "POST", path + "/messages", {"body": "Лишнее", "client_key": str(uuid4())})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_messages").fetchone()[0] == 30
        assert db.execute("SELECT MAX(count) FROM security_rate_limits").fetchone()[0] >= 31


def test_new_request_limit_and_public_pagination(community):
    app, clients, _ = community
    publish(clients)
    public_ids = []
    # Isolated synthetic rows keep this pagination/limit test fast and do not
    # bypass permission checks on the request-under-test.
    with database(app.state.db_path) as db:
        for index in range(22):
            user_id = db.execute("INSERT INTO users(role,email,name,password_hash) VALUES('candidate',?,'Private fixture','unused')",
                                 (f"fixture-{index}@community.example.invalid",)).lastrowid
            public_id = uuid4().hex
            public_ids.append(public_id)
            db.execute("""INSERT INTO community_profiles(user_id,public_id,public_name,headline,about,status,consent_at,
                       consent_version,consent_content_version,reviewed_content_version,published_at,created_at,updated_at)
                       VALUES(?,?,?,'Наставник','Опыт для тестирования каталога','published',?, ?,1,1,?,?,?)""",
                       (user_id, public_id, f"Коллега {index}", "2026-01-01", CONSENT_VERSION, "2026-01-01", "2026-01-01", "2026-01-01"))
    first_page = clients["visitor"].get("/api/community/people").json()
    second_page = clients["visitor"].get("/api/community/people?page=2").json()
    assert first_page["total"] == 23 and first_page["has_more"] and len(first_page["people"]) == 20
    assert len(second_page["people"]) == 3 and not second_page["has_more"]
    assert not ({item["public_id"] for item in first_page["people"]} & {item["public_id"] for item in second_page["people"]})
    for public_id in public_ids[:10]:
        assert mutate(clients["first"], "POST", "/api/community/connections", {"public_id": public_id, "purpose": "exchange"}).status_code == 200
    limited = mutate(clients["first"], "POST", "/api/community/connections", {"public_id": public_ids[10], "purpose": "exchange"})
    assert limited.status_code == 429
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_connections").fetchone()[0] == 10
    # Idempotent retry remains available after the daily new-request limit.
    assert mutate(clients["first"], "POST", "/api/community/connections", {"public_id": public_ids[0], "purpose": "exchange"}).status_code == 200


def test_additive_schema_can_run_repeatedly_without_republishing_or_losing_history(community):
    app, clients, _ = community
    original = publish(clients)
    with database(app.state.db_path) as db:
        before = db.execute("SELECT COUNT(*) FROM community_profile_events").fetchone()[0]
        for _ in range(2):
            for statement in COMMUNITY_DDL:
                db.execute(statement)
        assert db.execute("SELECT COUNT(*) FROM community_profile_events").fetchone()[0] == before
    assert clients["first"].get("/api/community/profile").json()["profile"] == original


def test_stale_tab_actor_guard_rejects_reads_saves_and_messages_after_account_change(community):
    app, clients, ids = community
    first = publish(clients, "first", public_name="Первый коллега")
    second = publish(clients, "second", public_name="Второй коллега")
    assert first["version"] == second["version"]  # CAS alone cannot detect an account switch.
    connection = connect(clients, second["public_id"])
    thread = "/api/community/connections/" + connection["id"]
    assert mutate(clients["second"], "POST", thread + "/respond", {"decision": "accept"}).status_code == 200
    browser = clients["first"]
    stale_headers = {**HEADERS, "X-Community-Actor": str(ids["first"])}
    assert browser.get("/api/community/profile", headers=stale_headers).status_code == 200
    # Simulate another tab replacing the shared cookie with user B's session.
    switched = mutate(browser, "POST", "/api/login", {
        "email": "second@community.example.invalid", "password": PASSWORD,
    })
    assert switched.status_code == 200
    paths = ("/api/community/profile", "/api/community/connections", thread, thread + "/messages",
             "/api/admin/community/profiles", "/api/admin/community/reports")
    for path in paths:
        result = browser.get(path, headers=stale_headers)
        assert result.status_code == 409, (path, result.text)
        assert "Аккаунт изменился в другой вкладке" in result.json()["detail"]
    stale_save = browser.put("/api/community/profile", headers=stale_headers, json={
        **PROFILE, "public_name": "Черновик первого человека", "expected_version": first["version"],
    })
    assert stale_save.status_code == 409
    message = {"body": "Личный текст из старой вкладки", "client_key": str(uuid4())}
    assert browser.post(thread + "/messages", headers=stale_headers, json=message).status_code == 409
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_messages").fetchone()[0] == 0
        assert db.execute("SELECT public_name,version FROM community_profiles WHERE user_id=?", (ids["second"],)).fetchone()["public_name"] == second["public_name"]
        assert db.execute("SELECT COUNT(*) FROM community_profile_events").fetchone()[0] == 6
    matching_headers = {**HEADERS, "X-Community-Actor": str(ids["second"])}
    assert browser.get("/api/community/profile", headers=matching_headers).json()["profile"] == second
    assert browser.put("/api/community/profile", headers=matching_headers, json={
        **{key: second[key] for key in PROFILE}, "expected_version": second["version"],
    }).status_code == 200
    assert browser.post(thread + "/messages", headers=matching_headers, json=message).status_code == 200
    # Public reads and existing API clients remain compatible without the guard.
    assert clients["visitor"].get("/api/community/people", headers=stale_headers).status_code == 200
    assert browser.get("/api/community/profile").status_code == 200


@pytest.mark.parametrize("operation", ["profile", "message"])
def test_commit_failure_never_reports_success_and_rolls_back_business_writes(community, operation):
    from app.main import get_connection

    app, clients, ids = community
    if operation == "message":
        publish(clients)
        second = publish(clients, "second")
        connection = connect(clients, second["public_id"])
        base = "/api/community/connections/" + connection["id"]
        accepted = mutate(clients["second"], "POST", base + "/respond", {"decision": "accept"})
        assert accepted.status_code == 200
        before_updated_at = accepted.json()["connection"]["updated_at"]
        method, path = "POST", base + "/messages"
        payload = {"body": "Сообщение не должно получить успешную квитанцию", "client_key": str(uuid4())}
    else:
        method, path = "PUT", "/api/community/profile"
        payload = {**PROFILE, "expected_version": 0}

    class RefuseCommit:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            raise RuntimeError("Synthetic database commit failure")

    def connection_with_failed_commit():
        # The underlying context manager would commit successfully during
        # dependency cleanup. The endpoint must attempt its own commit before
        # producing a success response, and propagate failure to this rollback.
        with database(app.state.db_path) as db:
            yield RefuseCommit(db)

    app.dependency_overrides[get_connection] = connection_with_failed_commit
    try:
        with TestClient(app, raise_server_exceptions=False) as failing_browser:
            failing_browser.cookies.update(clients["first"].cookies)
            response = failing_browser.request(method, path, headers=HEADERS, json=payload)
        assert response.status_code == 500
    finally:
        app.dependency_overrides.pop(get_connection, None)
    with database(app.state.db_path) as db:
        if operation == "message":
            assert db.execute("SELECT COUNT(*) FROM community_messages").fetchone()[0] == 0
            row = db.execute("SELECT updated_at FROM community_connections WHERE id=?", (connection["id"],)).fetchone()
            assert row["updated_at"] == before_updated_at
        else:
            assert db.execute("SELECT COUNT(*) FROM community_profiles WHERE user_id=?", (ids["first"],)).fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM community_profile_events").fetchone()[0] == 0
