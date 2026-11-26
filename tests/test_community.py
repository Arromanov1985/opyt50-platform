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
    public_page = visitor.get("/people/" + profile["public_id"])
    assert public_page.status_code == 200 and public_page.headers["cache-control"] == "no-store"
    assert '<dt>Город</dt><dd>Подольск</dd>' in public_page.text
    assert '<dt>Цель знакомства</dt><dd>Наставничество</dd>' in public_page.text
    assert public_page.text.index('person-skills') < public_page.text.index('id="person-next-step"')
    assert public_page.text.index('id="person-next-step"') < public_page.text.index('class="panel person-story"')
    assert 'id="request-connection"' in public_page.text and 'id="report-person"' in public_page.text
    assert "не подтверждает квалификацию" in public_page.text
    assert visitor.get("/api/community/people?q=НАСТАВНИК&city=ПОДОЛЬСК&goal=mentoring").json()["total"] == 1
    assert visitor.get("/api/community/people?q=бухгалтер").json()["people"] == []
    assert visitor.get("/api/community/people?page=0").status_code == 422
    for private in ("Закрытое имя", "+79991234567", "first@community", "user_id", "consent_at", "version"):
        assert private not in public.text
        assert private not in public_page.text
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


def test_privacy_request_hides_public_community_profile_and_stops_new_actions(community):
    """Restriction affects newly merged public community, not just vacancies."""
    app, clients, ids = community
    first = publish(clients)
    second = publish(clients, "second", public_name="Второй коллега")
    visitor = clients["visitor"]
    assert visitor.get("/api/community/people/" + first["public_id"]).status_code == 200
    connection = connect(clients, second["public_id"])
    path = "/api/community/connections/" + connection["id"]
    assert mutate(clients["second"], "POST", path + "/respond",
                  {"decision": "accept"}).status_code == 200
    assert mutate(clients["first"], "POST", path + "/messages",
                  {"body": "До запроса", "client_key": str(uuid4())}).status_code == 200

    request = mutate(clients["first"], "POST", "/api/account/privacy-requests",
                     {"kind": "stop_processing"})
    assert request.status_code == 201, request.text
    assert visitor.get("/api/community/people/" + first["public_id"]).status_code == 404
    assert visitor.get("/people/" + first["public_id"]).status_code == 404
    people = visitor.get("/api/community/people").json()
    assert people["total"] == 1 and people["people"][0]["public_id"] == second["public_id"]
    assert mutate(clients["first"], "PUT", "/api/community/profile",
                  {**PROFILE, "expected_version": first["version"]}).status_code == 409
    assert mutate(clients["first"], "POST", "/api/community/profile/submit",
                  {"expected_version": first["version"], "publish_consent": True}).status_code == 409
    assert mutate(clients["first"], "POST", "/api/community/connections",
                  {"public_id": second["public_id"], "purpose": "mentoring"}).status_code == 409
    assert mutate(clients["first"], "POST", path + "/messages",
                  {"body": "Новое сообщение", "client_key": str(uuid4())}).status_code == 409
    assert mutate(clients["second"], "POST", path + "/messages",
                  {"body": "Ответ после ограничения", "client_key": str(uuid4())}).status_code == 403
    assert clients["first"].get(path + "/messages").status_code == 200
    assert clients["first"].get("/api/account/privacy-requests").status_code == 200
    assert clients["first"].get("/api/account/data-export").status_code == 200
    assert mutate(clients["first"], "POST", path + "/block").status_code == 200
    withdrawn = mutate(clients["first"], "DELETE", "/api/community/profile/publication",
                       {"expected_version": first["version"]})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["profile"]["status"] == "hidden"
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_messages").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM community_profiles WHERE user_id=?",
                          (ids["first"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM privacy_rights_requests WHERE user_id=?",
                          (ids["first"],)).fetchone()[0] == 1


def test_community_attention_is_private_monotonic_and_explicit(community):
    app, clients, ids = community
    publish(clients, "first")
    second = publish(clients, "second", public_name="Второй коллега")
    connection = connect(clients, second["public_id"])
    path = "/api/community/connections/" + connection["id"]
    activity = "/api/community/activity"
    inbox = "/api/community/connections?attention=true"
    assert clients["visitor"].get(activity).status_code == 401
    assert clients["admin"].get(activity).status_code == 403
    assert clients["first"].get(activity).json()["pending_requests"] == 0
    assert clients["second"].get(activity).json()["pending_requests"] == 1
    assert clients["second"].get(inbox).json()["total"] == 1
    assert clients["first"].get(inbox).json()["total"] == 0
    assert mutate(clients["second"], "POST", path + "/respond",
                  {"decision": "accept"}).status_code == 200
    assert clients["second"].get(activity).json()["pending_requests"] == 0

    def send(sender, body):
        response = mutate(clients[sender], "POST", path + "/messages",
                          {"body": body, "client_key": str(uuid4())})
        assert response.status_code == 200, response.text
        return response.json()["message"]

    first_message = send("first", "Первое сообщение")
    own_message = send("second", "Ответ получателя")
    shown = clients["second"].get(path + "/messages").json()
    assert shown["unread_count"] == 1
    assert shown["messages"][-1]["id"] == own_message["id"]
    assert clients["first"].get(activity).json()["unread_messages"] == 1
    assert clients["second"].get(path).json()["connection"]["unread_count"] == 1
    assert clients["outsider"].get(activity).json()["unread_messages"] == 0
    assert clients["outsider"].get(path).status_code == 404
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_read_state").fetchone()[0] == 0

    # A message arrives after the last successful history fetch. Marking that
    # displayed cursor must not hide the message that the recipient has not seen.
    new_message = send("first", "Новое сообщение")
    mark = {"through_message_id": own_message["id"]}
    assert mutate(clients["outsider"], "POST", path + "/read", mark).status_code == 404
    assert mutate(clients["second"], "POST", path + "/read",
                  {"through_message_id": "not-in-thread"}).status_code == 422
    stale = clients["second"].post(path + "/read",
        headers={**HEADERS, "X-Community-Actor": str(ids["first"])}, json=mark)
    assert stale.status_code == 409
    marked = mutate(clients["second"], "POST", path + "/read", mark)
    assert marked.status_code == 200, marked.text
    assert marked.json()["unread_count"] == 1
    assert clients["second"].get(activity).json() == {
        "pending_requests": 0, "unread_messages": 1, "unread_threads": 1, "restricted": False
    }
    assert clients["second"].get(inbox).json()["total"] == 1
    assert clients["first"].get(activity).json()["unread_messages"] == 1
    assert mutate(clients["second"], "POST", path + "/read",
                  {"through_message_id": new_message["id"]}).json()["unread_count"] == 0
    assert mutate(clients["second"], "POST", path + "/read",
                  {"through_message_id": first_message["id"]}).json()["unread_count"] == 0
    assert clients["second"].get(inbox).json()["total"] == 0
    export = clients["second"].get("/api/account/data-export").json()["sections"]["my_community_read_state"]
    assert export[0]["through_message_id"] == new_message["id"]
    assert clients["first"].get("/api/account/data-export").json()["sections"]["my_community_read_state"] == []
    assert "read_at" not in clients["first"].get(path + "/messages").text
    assert "through_message_id" not in clients["first"].get(path).text
    send("first", "До блокировки")
    assert clients["second"].get(activity).json()["unread_messages"] == 1
    assert mutate(clients["second"], "POST", path + "/block").status_code == 200
    assert clients["second"].get(activity).json()["unread_messages"] == 0
    assert clients["second"].get(inbox).json()["total"] == 0
    assert clients["second"].get(path + "/messages").status_code == 200
    assert mutate(clients["second"], "POST", path + "/read", mark).status_code == 409


def test_attention_filter_precedes_pagination_and_respects_privacy(community):
    app, clients, ids = community
    owner = ids["second"]
    pending_id = uuid4().hex
    with database(app.state.db_path) as db:
        db.execute(
            """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
               purpose,status,created_at,updated_at) VALUES(?,?,?,?,?,'exchange','pending',?,?)""",
            (pending_id, ids["first"], owner, min(ids["first"], owner), max(ids["first"], owner),
             "2026-01-01", "2026-01-01"),
        )
        for index in range(21):
            peer = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'candidate','Test')",
                (f"attention-page-{index}@example.invalid", "test-hash"),
            ).lastrowid
            db.execute(
                """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
                   purpose,status,created_at,updated_at) VALUES(?,?,?,?,?,'exchange','accepted',?,?)""",
                (uuid4().hex, owner, peer, min(owner, peer), max(owner, peer),
                 "2026-02-01", "2026-02-01"),
            )
    ordinary = clients["second"].get("/api/community/connections").json()
    assert ordinary["total"] == 22
    assert pending_id not in {item["id"] for item in ordinary["connections"]}
    filtered = clients["second"].get("/api/community/connections?attention=true").json()
    assert filtered["total"] == 1
    assert filtered["connections"][0]["id"] == pending_id

    request = mutate(clients["first"], "POST", "/api/account/privacy-requests",
                     {"kind": "stop_processing"})
    assert request.status_code == 201
    assert clients["second"].get("/api/community/activity").json()["pending_requests"] == 0
    assert clients["second"].get("/api/community/connections?attention=true").json()["total"] == 0
    assert clients["first"].get("/api/community/activity").json()["restricted"] is True
    assert clients["first"].get("/api/community/connections").json()["total"] == 1

def feed_payload(**changes):
    return {"client_key": str(uuid4()), "kind": "experience",
            "title": "Передача опыта на складе", "body": "Полезно начать с плана обучения.",
            "publish_consent": True, **changes}


def submit_feed(client, **changes):
    response = mutate(client, "POST", "/api/community/feed", feed_payload(**changes))
    assert response.status_code == 200, response.text
    return response.json()["entry"]


def moderate_feed(admin, entry, decision="approve", reason=""):
    response = mutate(admin, "PATCH", "/api/admin/community/feed/" + entry["id"],
                      {"expected_version": entry["version"], "decision": decision, "reason": reason})
    assert response.status_code == 200, response.text
    return response.json()["entry"]


def test_feed_consent_moderation_ownership_and_discussion(community):
    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    url = "/api/community/feed"
    assert clients["visitor"].get(url).status_code == 401
    assert clients["outsider"].get("/api/admin/community/feed").status_code == 403
    assert mutate(first, "POST", url, feed_payload()).status_code == 403
    publish(clients, "first", public_name="Автор опыта")
    publish(clients, "second", public_name="Автор ответа")
    assert mutate(first, "POST", url, feed_payload(publish_consent=False)).status_code == 422
    assert mutate(first, "POST", url, feed_payload(body="Пишите на test@example.invalid")).status_code == 422
    assert mutate(clients["employer"], "POST", url, feed_payload()).status_code == 403
    payload = feed_payload()
    response = mutate(first, "POST", url, payload)
    assert response.status_code == 200, response.text
    entry = response.json()["entry"]
    assert entry["status"] == "pending"
    assert mutate(first, "POST", url, payload).json()["entry"] == entry
    assert mutate(first, "POST", url, {**payload, "body": "Другой текст"}).status_code == 409
    assert second.get(url).json()["entries"] == []
    assert second.get(url + "/mine").json()["entries"] == []
    assert second.get(url + "/" + entry["id"] + "/comments").status_code == 404
    assert mutate(second, "DELETE", url + "/" + entry["id"], {"expected_version": entry["version"]}).status_code == 404
    assert first.get(url + "/mine").json()["entries"] == [entry]
    assert admin.get("/api/admin/community/feed").json()["entries"][0]["id"] == entry["id"]
    approved = moderate_feed(admin, entry)
    assert approved["status"] == "published"
    assert mutate(admin, "PATCH", "/api/admin/community/feed/" + entry["id"],
                  {"expected_version": entry["version"], "decision": "approve"}).status_code == 409
    visible = second.get(url + "?kind=experience&q=ОБУЧЕНИЯ")
    assert visible.status_code == 200
    item = visible.json()["entries"][0]
    assert item["id"] == entry["id"] and item["public_name"] == "Автор опыта"
    assert set(item) == {"id", "parent_id", "kind", "title", "body", "created_at", "published_at",
                         "public_id", "public_name", "headline"}
    assert "no-store" in visible.headers["cache-control"]
    assert clients["employer"].get(url).json()["entries"][0]["id"] == entry["id"]
    assert second.get(url + "?kind=projects").json()["entries"] == []

    comment = submit_feed(second, parent_id=entry["id"], kind="comment", title="", body="Согласен с этим подходом.")
    discussion = url + "/" + entry["id"] + "/comments"
    assert first.get(discussion).json()["entries"] == []
    assert mutate(second, "POST", url, feed_payload(parent_id=comment["id"], kind="comment", title="")).status_code == 404
    queued = admin.get("/api/admin/community/feed").json()["entries"][0]
    assert queued["parent_title"] == entry["title"]
    assert queued["parent_body"] == entry["body"]
    moderate_feed(admin, comment)
    assert first.get(discussion).json()["entries"][0]["id"] == comment["id"]
    assert first.get(url).json()["entries"][0]["id"] == entry["id"]
    assert len(first.get(url).json()["entries"]) == 1
    export = second.get("/api/account/data-export").json()["sections"]["my_community_feed"]
    assert [item["id"] for item in export] == [comment["id"]]

    hidden = mutate(first, "DELETE", url + "/" + entry["id"], {"expected_version": approved["version"]})
    assert hidden.status_code == 200, hidden.text
    assert second.get(discussion).status_code == 404
    assert second.get(url).json()["entries"] == []
    assert mutate(second, "POST", url, feed_payload(parent_id=entry["id"], kind="comment", title="")).status_code == 404
    assert second.get(url + "/mine").json()["entries"][0]["id"] == comment["id"]
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_feed_entries").fetchone()[0] == 2


def test_feed_filters_blocks_and_privacy_before_pagination(community):
    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    first_profile = publish(clients, "first", public_name="Автор проектов")
    second_profile = publish(clients, "second", public_name="Автор советов")
    first_post = moderate_feed(admin, submit_feed(first, kind="projects"))
    second_post = moderate_feed(admin, submit_feed(second, kind="mentoring"))
    url = "/api/community/feed"
    assert len(clients["outsider"].get(url).json()["entries"]) == 2
    connection = connect(clients, second_profile["public_id"])
    assert mutate(first, "POST", "/api/community/connections/" + connection["id"] + "/block").status_code == 200
    assert [item["id"] for item in first.get(url).json()["entries"]] == [first_post["id"]]
    assert [item["id"] for item in second.get(url).json()["entries"]] == [second_post["id"]]
    assert first.get(url + "/" + second_post["id"] + "/comments").status_code == 404
    assert mutate(first, "POST", url, feed_payload(parent_id=second_post["id"], kind="comment", title="")).status_code == 404
    request = mutate(first, "POST", "/api/account/privacy-requests", {"kind": "stop_processing"})
    assert request.status_code == 201, request.text
    assert [item["id"] for item in clients["outsider"].get(url).json()["entries"]] == [second_post["id"]]
    assert first.get(url).status_code == 403
    assert clients["visitor"].get("/people/" + first_profile["public_id"]).status_code == 404

    with database(app.state.db_path) as db:
        for index in range(21):
            db.execute(
                """INSERT INTO community_feed_entries(
                   id,author_id,client_key,kind,title,body,status,consent_at,consent_version,
                   published_at,created_at,updated_at) VALUES(?,?,?,'experience',?,?,'published',
                   '2026-01-01','test','2026-01-02','2026-01-01','2026-01-02')""",
                (uuid4().hex, ids["second"], str(uuid4()), "Совет", "Профессиональный опыт"),
            )
    page1 = clients["outsider"].get(url + "?kind=experience").json()
    page2 = clients["outsider"].get(url + "?kind=experience&page=2").json()
    assert len(page1["entries"]) == 20 and page1["has_more"]
    assert len(page2["entries"]) == 1 and not page2["has_more"]
    assert page2["entries"][0]["id"] not in {item["id"] for item in page1["entries"]}


def test_feed_privacy_impact_includes_other_authors_comments(community):
    from app.privacy_disposal import impact_preview

    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    publish(clients, "first")
    publish(clients, "second")
    root = moderate_feed(admin, submit_feed(first))
    moderate_feed(admin, submit_feed(second, parent_id=root["id"], kind="comment", title=""))
    submit_feed(first, parent_id=root["id"], kind="comment", title="")
    response = mutate(first, "POST", "/api/account/privacy-requests", {"kind": "deletion"})
    assert response.status_code == 201, response.text
    with database(app.state.db_path) as db:
        request = db.execute("SELECT request_key FROM privacy_rights_requests WHERE user_id=?",
                             (ids["first"],)).fetchone()
        preview = impact_preview(db, request["request_key"])
        assert preview["counts"]["community_feed_entries"] == 2
        assert preview["counts"]["community_feed_linked_comments"] == 1
        assert any("комментарии других участников" in risk for risk in preview["risk_flags"])
        assert preview["automatic_deletion"] is False


def test_feed_following_is_private_and_filters_before_pagination(community):
    app, clients, ids = community
    first, second, outsider, employer, admin = (clients[key] for key in
        ("first", "second", "outsider", "employer", "admin"))
    p1 = publish(clients, "first", public_name="Первый автор")
    p2 = publish(clients, "second", public_name="Второй автор")
    a = moderate_feed(admin, submit_feed(first, kind="projects"))
    b = moderate_feed(admin, submit_feed(second, kind="mentoring"))
    url = "/api/community/feed"
    follows = url + "/follows"
    assert clients["visitor"].get(follows).status_code == 401
    assert admin.get(follows).status_code == 403
    assert mutate(first, "POST", follows, {"public_id": p1["public_id"]}).status_code == 422
    assert mutate(first, "POST", follows, {"public_id": "unknown"}).status_code == 404
    payload = {"public_id": p2["public_id"]}
    created = mutate(first, "POST", follows, payload)
    assert created.status_code == 200, created.text
    assert mutate(first, "POST", follows, payload).json() == created.json()
    own = first.get(follows).json()["follows"]
    assert len(own) == 1 and own[0]["public_name"] == "Второй автор"
    assert set(own[0]) == {"public_id", "public_name", "headline", "available", "created_at"}
    assert second.get(follows).json()["follows"] == []
    assert outsider.get(follows + "/" + p2["public_id"]).json()["following"] is False
    assert first.get(follows + "/" + p2["public_id"]).json()["following"] is True
    assert mutate(employer, "POST", follows, payload).status_code == 200
    assert [item["id"] for item in first.get(url + "?following=true").json()["entries"]] == [b["id"]]
    assert [item["id"] for item in first.get(url + "?following=true&kind=projects").json()["entries"]] == []
    assert outsider.get(url + "?following=true").json()["entries"] == []
    assert first.get(url).json()["following_public_ids"] == [p2["public_id"]]
    assert second.get(url).json()["following_public_ids"] == []
    export = first.get("/api/account/data-export").json()["sections"]["my_community_follows"]
    assert len(export) == 1 and export[0]["public_id"] == p2["public_id"]

    # A block makes the subscription inactive in the personalized feed, not public.
    connection = connect(clients, p2["public_id"])
    assert mutate(first, "POST", "/api/community/connections/" + connection["id"] + "/block").status_code == 200
    assert first.get(url + "?following=true").json()["entries"] == []
    inactive = first.get(follows).json()["follows"][0]
    assert not inactive["available"] and inactive["public_name"] is None
    assert mutate(first, "POST", follows, payload).status_code == 404
    assert mutate(first, "DELETE", follows + "/" + p2["public_id"]).status_code == 200
    assert mutate(first, "DELETE", follows + "/" + p2["public_id"]).status_code == 200
    assert first.get(follows).json()["follows"] == []
    assert employer.get(follows).json()["follows"][0]["public_id"] == p2["public_id"]
    assert a["id"] in {entry["id"] for entry in first.get(url).json()["entries"]}


def test_feed_alerts_are_explicit_private_and_visibility_aware(community):
    app, clients, ids = community
    first, second, outsider, admin = (clients[key] for key in
        ("first", "second", "outsider", "admin"))
    publish(clients, "first")
    publish(clients, "second")
    root = moderate_feed(admin, submit_feed(first))
    reply = submit_feed(second, parent_id=root["id"], kind="comment", title="")
    url = "/api/community/feed/alerts"
    assert first.get(url).json()["entries"] == []
    moderate_feed(admin, reply)
    assert second.get(url).json()["entries"] == []
    assert outsider.get(url).json()["entries"] == []
    assert mutate(outsider, "POST", url + "/" + reply["id"] + "/read").status_code == 404
    first_alert = first.get(url).json()["entries"][0]
    assert first_alert["id"] == reply["id"] and first_alert["root_title"] == root["title"]
    assert first_alert["parent_id"] == root["id"]
    first.get("/api/community/feed/" + root["id"] + "/comments")
    assert first.get(url).json()["entries"][0]["id"] == reply["id"]
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_feed_alert_reads").fetchone()[0] == 0
    assert mutate(first, "POST", url + "/" + reply["id"] + "/read").status_code == 200
    assert mutate(first, "POST", url + "/" + reply["id"] + "/read").status_code == 200
    assert first.get(url).json()["entries"] == []
    own_reply = moderate_feed(admin, submit_feed(first, parent_id=root["id"], kind="comment", title=""))
    assert first.get(url).json()["entries"] == []
    assert mutate(first, "POST", url + "/" + own_reply["id"] + "/read").status_code == 404
    another = moderate_feed(admin, submit_feed(second, parent_id=root["id"], kind="comment", title=""))
    assert first.get(url).json()["entries"][0]["id"] == another["id"]
    assert first.get("/api/account/data-export").json()["sections"]["my_community_feed_alert_reads"][0]["entry_id"] == reply["id"]
    assert second.get("/api/account/data-export").json()["sections"]["my_community_feed_alert_reads"] == []
    assert mutate(first, "DELETE", "/api/community/feed/" + root["id"],
                  {"expected_version": root["version"]}).status_code == 200
    assert first.get(url).json()["entries"] == []


def test_feed_reports_are_private_and_require_explicit_moderation(community):
    app, clients, ids = community
    first, second, outsider, admin = (clients[key] for key in
        ("first", "second", "outsider", "admin"))
    publish(clients, "first")
    publish(clients, "second")
    pending = submit_feed(first)
    base = "/api/community/feed"
    review = "/api/admin/community/feed/reports"
    report_url = base + "/" + pending["id"] + "/reports"
    payload = {"reason": "spam", "details": "Проверьте контекст."}
    assert mutate(second, "POST", report_url, payload).status_code == 404
    root = moderate_feed(admin, pending)
    assert mutate(first, "POST", report_url, payload).status_code == 422
    response = mutate(second, "POST", report_url, payload)
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert mutate(second, "POST", report_url, payload).json()["report"] == report
    assert outsider.get(base).json()["entries"][0]["id"] == root["id"]
    assert first.get(review).status_code == 403
    queued = admin.get(review).json()["reports"][0]
    assert queued["id"] == report["id"] and queued["entry"]["body"] == root["body"]
    assert "reporter_id" not in queued
    assert first.get("/api/account/data-export").json()["sections"]["my_community_feed_reports"] == []
    assert second.get("/api/account/data-export").json()["sections"]["my_community_feed_reports"][0]["id"] == report["id"]
    assert mutate(admin, "PATCH", review + "/" + report["id"], {"decision": "hide"}).status_code == 422
    result = mutate(admin, "PATCH", review + "/" + report["id"],
                    {"decision": "hide", "reason": "Нарушение правил сообщества"})
    assert result.status_code == 200, result.text
    assert result.json()["report"]["status"] == "resolved"
    assert outsider.get(base).json()["entries"] == []
    assert first.get(base + "/mine").json()["entries"][0]["status"] == "hidden"
    assert mutate(admin, "PATCH", review + "/" + report["id"], {"decision": "dismiss"}).status_code == 409
    assert admin.get(review).json()["reports"] == []
    assert admin.get(review + "?status=resolved").json()["reports"][0]["id"] == report["id"]

    # Individual comments can also be reported; hiding one leaves its root intact.
    root2 = moderate_feed(admin, submit_feed(first))
    reply = moderate_feed(admin, submit_feed(second, parent_id=root2["id"], kind="comment", title=""))
    reported = mutate(first, "POST", base + "/" + reply["id"] + "/reports",
                      {"reason": "other"}).json()["report"]
    assert mutate(admin, "PATCH", review + "/" + reported["id"],
                  {"decision": "dismiss"}).status_code == 200
    assert first.get(base + "/" + root2["id"] + "/comments").json()["entries"][0]["id"] == reply["id"]
    assert first.get(base + "/alerts").json()["entries"][0]["id"] == reply["id"]


def test_structured_opportunities_moderation_filtering_and_safe_connection(community):
    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    profile = publish(clients, "first", public_name="Опытный наставник")
    peer = publish(clients, "second", public_name="Участник проекта", city="Москва")
    offer = {"intent": "offer", "meeting_format": "online", "commitment": "regular"}
    search = "/api/community/opportunities?kind=mentoring"
    assert clients["visitor"].get(search).status_code == 401
    assert admin.get(search).status_code == 403
    assert first.get(search).json()["can_publish"] is True
    assert clients["employer"].get(search).json()["can_publish"] is False
    assert mutate(first, "POST", "/api/community/feed", feed_payload(
        kind="projects", opportunity=offer)).status_code == 422
    assert mutate(first, "POST", "/api/community/feed", feed_payload(
        kind="mentoring", opportunity=offer, publish_consent=False)).status_code == 422
    payload = feed_payload(kind="mentoring", opportunity=offer,
                           title="Помогу освоить учёт", body="Передача практического опыта")
    response = mutate(first, "POST", "/api/community/feed", payload)
    assert response.status_code == 200, response.text
    pending = response.json()["entry"]
    assert pending["opportunity"] == offer
    assert mutate(first, "POST", "/api/community/feed", payload).json()["entry"] == pending
    assert mutate(first, "POST", "/api/community/feed", {
        **payload, "opportunity": {**offer, "meeting_format": "offline"}
    }).status_code == 409
    assert second.get(search).json()["entries"] == []
    connection_payload = {"public_id": profile["public_id"], "purpose": "mentoring",
                          "opportunity_id": pending["id"], "note": "Хочу обсудить обучение"}
    assert mutate(second, "POST", "/api/community/connections", connection_payload).status_code == 404
    queue = admin.get("/api/admin/community/feed").json()["entries"]
    assert next(row for row in queue if row["id"] == pending["id"])["opportunity"] == offer
    approved = moderate_feed(admin, pending)
    plain = moderate_feed(admin, submit_feed(first, kind="mentoring"))
    project = moderate_feed(admin, submit_feed(second, kind="projects", opportunity={
        "intent": "organize", "meeting_format": "hybrid", "commitment": "flexible"
    }))
    assert second.get(search + "&intent=organize").status_code == 422
    result = second.get(search + "&intent=offer&meeting_format=online&commitment=regular&city=Подольск&q=склад")
    assert result.status_code == 200, result.text
    assert [row["id"] for row in result.json()["entries"]] == [approved["id"]]
    item = result.json()["entries"][0]
    assert item["opportunity"] == {**offer, "city": "Подольск"}
    assert "author_id" not in item and "email" not in item and "phone" not in item
    assert second.get(search + "&city=Москва").json()["entries"] == []
    assert second.get(search + "&meeting_format=offline").json()["entries"] == []
    assert [row["id"] for row in second.get("/api/community/opportunities?kind=projects").json()["entries"]] == [project["id"]]
    assert [row["id"] for row in first.get("/api/community/feed/mine?opportunity_kind=mentoring").json()["entries"]] == [approved["id"]]
    feed = second.get("/api/community/feed?kind=mentoring").json()["entries"]
    assert {row["id"] for row in feed} == {approved["id"], plain["id"]}
    assert "opportunity" not in next(row for row in feed if row["id"] == plain["id"])
    assert mutate(second, "POST", "/api/community/connections", {
        **connection_payload, "purpose": "projects"
    }).status_code == 404
    assert mutate(second, "POST", "/api/community/connections", {
        **connection_payload, "opportunity_id": plain["id"]
    }).status_code == 404
    assert mutate(clients["employer"], "POST", "/api/community/connections", {
        **connection_payload, "public_id": peer["public_id"]
    }).status_code == 404
    connected = mutate(second, "POST", "/api/community/connections", connection_payload)
    assert connected.status_code == 200, connected.text
    connection = connected.json()["connection"]
    assert connection["status"] == "pending" and connection["purpose"] == "mentoring"
    assert mutate(second, "POST", "/api/community/connections", connection_payload).json()["connection"]["id"] == connection["id"]
    assert mutate(first, "DELETE", "/api/community/feed/" + approved["id"],
                  {"expected_version": approved["version"]}).status_code == 200
    assert second.get(search).json()["entries"] == []
    assert mutate(second, "POST", "/api/community/connections", connection_payload).status_code == 404
    assert second.get("/api/community/connections/" + connection["id"]).status_code == 200
    exported = first.get("/api/account/data-export").json()["sections"]["my_community_opportunities"]
    assert exported == [{"entry_id": approved["id"], **offer}]
    with database(app.state.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM community_opportunities").fetchone()[0] == 2


def test_opportunities_follow_profile_privacy_and_pagination(community):
    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    publish(clients, "first")
    profile = publish(clients, "second", city="Москва")
    project = {"intent": "join", "meeting_format": "offline", "commitment": "one_off"}
    approved = moderate_feed(admin, submit_feed(second, kind="projects", opportunity=project))
    search = "/api/community/opportunities?kind=projects&intent=join"
    with database(app.state.db_path) as db:
        for index in range(21):
            entry = uuid4().hex
            db.execute(
                """INSERT INTO community_feed_entries(
                   id,author_id,client_key,kind,title,body,status,consent_at,consent_version,
                   published_at,created_at,updated_at) VALUES(?,?,?,'projects',?,?,'published',
                   '2026-01-01','test','2026-01-02','2026-01-01','2026-01-02')""",
                (entry, ids["second"], uuid4().hex, "Проект", "Совместная работа"),
            )
            db.execute("INSERT INTO community_opportunities VALUES(?,'join','offline','one_off')", (entry,))
    page1 = first.get(search).json()
    page2 = first.get(search + "&page=2").json()
    assert len(page1["entries"]) == 20 and page1["has_more"]
    assert len(page2["entries"]) == 2 and not page2["has_more"]
    assert not ({row["id"] for row in page1["entries"]} & {row["id"] for row in page2["entries"]})
    connection = connect(clients, profile["public_id"])
    assert mutate(first, "POST", "/api/community/connections/" + connection["id"] + "/block").status_code == 200
    assert first.get(search).json()["entries"] == []
    assert mutate(first, "POST", "/api/community/connections", {
        "public_id": profile["public_id"], "purpose": "projects", "opportunity_id": approved["id"]
    }).status_code == 404
    assert mutate(second, "POST", "/api/account/privacy-requests", {"kind": "stop_processing"}).status_code == 201
    assert clients["outsider"].get(search).json()["entries"] == []


def test_saved_entries_are_private_and_hidden_content_never_reappears(community):
    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    profile = publish(clients, "first")
    publish(clients, "second")
    pending = submit_feed(first, title="Закрытая тема")
    root = moderate_feed(admin, submit_feed(first, title="Полезный материал"))
    comment = moderate_feed(admin, submit_feed(first, kind="comment", parent_id=root["id"], title=""))
    saved = "/api/community/feed/saved"
    assert clients["visitor"].get(saved).status_code == 401
    assert admin.get(saved).status_code == 403
    assert mutate(second, "PUT", saved + "/" + pending["id"]).status_code == 404
    assert mutate(second, "PUT", saved + "/" + comment["id"]).status_code == 404
    target = saved + "/" + root["id"]
    assert mutate(second, "PUT", target).json() == {"entry_id": root["id"], "saved": True}
    assert mutate(second, "PUT", target).status_code == 200
    record = second.get(saved).json()["records"][0]
    assert record["entry"]["title"] == root["title"]
    assert second.get("/api/community/feed").json()["saved_entry_ids"] == [root["id"]]
    assert first.get(saved).json()["records"] == []
    assert clients["outsider"].get(saved).json()["records"] == []
    assert first.get("/api/community/feed").json()["saved_entry_ids"] == []
    assert len(second.get("/api/account/data-export").json()["sections"]["my_community_saved_entries"]) == 1
    assert first.get("/api/account/data-export").json()["sections"]["my_community_saved_entries"] == []
    assert mutate(clients["outsider"], "DELETE", target).status_code == 200
    assert len(second.get(saved).json()["records"]) == 1
    assert mutate(first, "DELETE", "/api/community/feed/" + root["id"], {
        "expected_version": root["version"]
    }).status_code == 200
    unavailable = second.get(saved).json()["records"][0]
    assert unavailable == {"entry_id": root["id"], "created_at": record["created_at"], "entry": None}
    assert mutate(second, "PUT", target).status_code == 404
    assert mutate(second, "DELETE", target).status_code == 200
    assert mutate(second, "DELETE", target).status_code == 200
    assert second.get(saved).json()["records"] == []
    assert profile["public_id"]


def test_explicit_discovery_preferences_and_matches_respect_privacy(community):
    app, clients, ids = community
    first, second, outsider, admin = (clients[key] for key in
        ("first", "second", "outsider", "admin"))
    profile = publish(clients, "first", headline="Наставник по складскому учёту",
                      city="Подольск", goal="mentoring")
    publish(clients, "second", city="Подольск", headline="Наставник склада")
    publish(clients, "outsider", headline="Специалист по бухгалтерии", skills="Бухгалтерский учёт",
            city="Москва", goal="projects")
    offer = {"intent": "offer", "meeting_format": "online", "commitment": "regular"}
    root = moderate_feed(admin, submit_feed(first, kind="mentoring", opportunity=offer,
                                            title="Передача опыта", body="Практическое обучение"))
    moderate_feed(admin, submit_feed(first, kind="mentoring"))
    moderate_feed(admin, submit_feed(second, kind="mentoring", opportunity=offer))
    url = "/api/community/recommendations"
    prefs = url + "/preferences"
    assert clients["visitor"].get(url).status_code == 401
    assert admin.get(url).status_code == 403
    initial = second.get(url).json()
    assert initial["settings"]["revision"] is None and initial["people"]["people"] == []
    assert initial["feed"]["entries"] == []
    assert mutate(second, "PUT", prefs, {}).status_code == 422
    assert mutate(second, "PUT", prefs, {"keyword": "test@example.invalid"}).status_code == 422
    saved = mutate(second, "PUT", prefs, {"keyword": "СКЛАД", "city": "подольск", "focus": "mentoring"})
    assert saved.status_code == 200, saved.text
    revision = saved.json()["settings"]["revision"]
    result = second.get(url).json()
    assert [row["public_id"] for row in result["people"]["people"]] == [profile["public_id"]]
    assert set(result["people"]["people"][0]) == set(PUBLIC_FIELDS)
    assert [row["id"] for row in result["feed"]["entries"]] == [root["id"]]
    assert result["settings"]["revision"] == revision
    assert first.get(url).json()["settings"]["revision"] is None
    assert outsider.get(url).json()["settings"]["revision"] is None
    assert mutate(second, "PUT", prefs, {"keyword": "другая тема"}).status_code == 409
    assert mutate(second, "DELETE", prefs, {"expected_revision": "stale"}).status_code == 409
    assert second.get("/api/account/data-export").json()["sections"]["my_community_discovery_preferences"][0]["keyword"] == "СКЛАД"
    assert first.get("/api/account/data-export").json()["sections"]["my_community_discovery_preferences"] == []
    saved_path = "/api/community/feed/saved/" + root["id"]
    assert mutate(second, "PUT", saved_path).status_code == 200
    connection = connect(clients, profile["public_id"], sender="second")
    assert mutate(second, "POST", "/api/community/connections/" + connection["id"] + "/block").status_code == 200
    hidden = second.get(url).json()
    assert hidden["people"]["people"] == [] and hidden["feed"]["entries"] == []
    assert second.get("/api/community/feed/saved").json()["records"][0]["entry"] is None
    cleared = mutate(second, "DELETE", prefs, {"expected_revision": revision})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["settings"]["revision"] is None
    assert second.get(url).json()["feed"]["entries"] == []
    assert len(second.get("/api/community/feed/saved").json()["records"]) == 1


def test_saved_pagination_and_linked_privacy_impact(community):
    from app.privacy_disposal import impact_preview

    app, clients, ids = community
    first, second, admin = clients["first"], clients["second"], clients["admin"]
    publish(clients, "first")
    with database(app.state.db_path) as db:
        for index in range(21):
            entry = uuid4().hex
            db.execute(
                """INSERT INTO community_feed_entries(
                   id,author_id,client_key,kind,title,body,status,consent_at,consent_version,
                   published_at,created_at,updated_at) VALUES(?,?,?,'experience',?,?,'published',
                   '2026-01-01','test','2026-01-02','2026-01-01','2026-01-02')""",
                (entry, ids["first"], uuid4().hex, "Совет", "Профессиональный опыт"),
            )
            db.execute("INSERT INTO community_saved_entries VALUES(?,?,?)",
                       (ids["second"], entry, f"2026-01-{index+1:02d}"))
    url = "/api/community/feed/saved"
    page1 = second.get(url).json()
    page2 = second.get(url + "?page=2").json()
    assert len(page1["records"]) == 20 and page1["has_more"]
    assert len(page2["records"]) == 1 and not page2["has_more"]
    assert all(row["entry"] is not None for row in page1["records"] + page2["records"])
    assert not ({row["entry_id"] for row in page1["records"]} & {row["entry_id"] for row in page2["records"]})
    request = mutate(first, "POST", "/api/account/privacy-requests", {"kind": "deletion"})
    assert request.status_code == 201, request.text
    assert all(row["entry"] is None for row in second.get(url).json()["records"])
    with database(app.state.db_path) as db:
        row = db.execute("SELECT request_key FROM privacy_rights_requests WHERE user_id=?", (ids["first"],)).fetchone()
        preview = impact_preview(db, row["request_key"])
        assert preview["counts"]["community_saved_entries_affected"] == 21
        assert preview["automatic_deletion"] is False


def portfolio_payload(**changes):
    return {"client_key": str(uuid4()), "kind": "project", "title": "Внедрение складского учёта",
            "period": "2020–2024", "contribution": "Разработал понятный порядок учёта и обучил коллег.",
            "result": "Снизили количество ошибок.", **changes}


def create_portfolio(client, **changes):
    response = mutate(client, "POST", "/api/community/portfolio", portfolio_payload(**changes))
    assert response.status_code == 200, response.text
    return response.json()["entry"]


def submit_portfolio(client, entry):
    response = mutate(client, "POST", "/api/community/portfolio/" + entry["id"] + "/submit",
                      {"expected_version": entry["version"], "publish_consent": True})
    assert response.status_code == 200, response.text
    return response.json()["entry"]


def approve_portfolio(admin, entry):
    response = mutate(admin, "PATCH", "/api/admin/community/portfolio/" + entry["id"],
                      {"expected_version": entry["version"], "decision": "approve"})
    assert response.status_code == 200, response.text
    return response.json()["entry"]


def test_portfolio_separate_drafts_consent_moderation_and_public_profile(community):
    app, clients, ids = community
    first, second, admin, visitor = (clients[key] for key in ("first", "second", "admin", "visitor"))
    url = "/api/community/portfolio"
    queue = "/api/admin/community/portfolio"
    assert visitor.get(url).status_code == 401
    assert clients["employer"].get(url).status_code == 403
    assert second.get(queue).status_code == 403
    assert first.get(url).json()["has_profile"] is False
    assert mutate(first, "POST", url, portfolio_payload()).status_code == 409
    draft_profile = save(first)
    assert first.get(url).json()["can_publish"] is False
    public_url = "/api/community/people/" + draft_profile["public_id"] + "/portfolio"
    page = "/people/" + draft_profile["public_id"]
    assert visitor.get(public_url).status_code == 404
    assert mutate(first, "POST", url, portfolio_payload(result="Пишите на test@example.invalid")).status_code == 422
    payload = portfolio_payload(contribution="Мой личный вклад. <img src=x onerror=window.portfolioXss=1>")
    response = mutate(first, "POST", url, payload)
    assert response.status_code == 200, response.text
    draft = response.json()["entry"]
    assert draft["status"] == "draft"
    assert mutate(first, "POST", url, payload).json()["entry"] == draft
    assert mutate(first, "POST", url, {**payload, "title": "Другой текст"}).status_code == 409
    assert second.get(url).json()["entries"] == []
    assert admin.get(queue).json()["entries"] == []
    assert mutate(admin, "PATCH", queue + "/" + draft["id"],
                  {"expected_version": draft["version"], "decision": "approve"}).status_code == 409
    assert mutate(first, "POST", url + "/" + draft["id"] + "/submit",
                  {"expected_version": draft["version"], "publish_consent": True}).status_code == 409
    profile = approve(admin, submit(first, draft_profile))
    assert first.get(url).json()["can_publish"] is True
    assert visitor.get(public_url).json()["entries"] == []
    assert draft["title"] not in visitor.get(page).text
    assert mutate(first, "POST", url + "/" + draft["id"] + "/submit",
                  {"expected_version": draft["version"], "publish_consent": False}).status_code == 400
    assert mutate(first, "POST", url + "/" + draft["id"] + "/submit",
                  {"expected_version": draft["version"], "publish_consent": "true"}).status_code == 422
    assert mutate(second, "DELETE", url + "/" + draft["id"] + "/publication",
                  {"expected_version": draft["version"]}).status_code == 404
    pending = submit_portfolio(first, draft)
    assert visitor.get(public_url).json()["entries"] == []
    assert admin.get(queue).json()["entries"][0]["id"] == draft["id"]
    published = approve_portfolio(admin, pending)
    assert published["status"] == "published"
    public = visitor.get(public_url)
    assert public.status_code == 200 and "no-store" in public.headers["cache-control"]
    entry = public.json()["entries"][0]
    assert set(entry) == {"id", "kind", "title", "period", "contribution", "result"}
    assert entry["id"] == draft["id"]
    html = visitor.get(page).text
    assert draft["title"] in html and "&lt;img" in html
    assert "<img src=x onerror=window.portfolioXss=1>" not in html
    assert "first@community.example.invalid" not in html
    assert "share-person" in html
    assert first.get("/api/community/profile").json()["profile"] == profile
    assert first.get("/api/account/data-export").json()["sections"]["my_community_portfolio"][0]["id"] == draft["id"]
    assert second.get("/api/account/data-export").json()["sections"]["my_community_portfolio"] == []
    assert mutate(first, "PUT", url + "/" + draft["id"],
                  {**{k: published[k] for k in ("kind", "title", "period", "contribution", "result")},
                   "expected_version": draft["version"]}).status_code == 409
    fields = {k: published[k] for k in ("kind", "title", "period", "contribution", "result")}
    edited = mutate(first, "PUT", url + "/" + draft["id"], {
        **fields, "result": "Новый результат работы", "expected_version": published["version"]})
    assert edited.status_code == 200, edited.text
    current = edited.json()["entry"]
    assert current["status"] == "draft" and current["consent_at"] is None
    assert visitor.get(public_url).json()["entries"] == []
    assert visitor.get(page).status_code == 200
    assert first.get("/api/community/profile").json()["profile"] == profile
    assert admin.get(queue).json()["entries"] == []
    assert admin.get(queue + "?status=published").json()["entries"] == []


def test_portfolio_parent_withdrawal_privacy_and_no_draft_profile_leak(community):
    app, clients, ids = community
    first, admin, visitor = (clients[key] for key in ("first", "admin", "visitor"))
    profile = publish(clients, "first")
    public_url = "/api/community/people/" + profile["public_id"] + "/portfolio"
    url = "/api/community/portfolio"
    queue = "/api/admin/community/portfolio"
    a = approve_portfolio(admin, submit_portfolio(first, create_portfolio(first)))
    b = submit_portfolio(first, create_portfolio(first, kind="achievement", title="Обучил команду"))
    draft = save(first, public_name="Непубличный черновик имени", headline="Непубличная профессия")
    assert visitor.get(public_url).status_code == 404
    pending = admin.get(queue).json()["entries"][0]
    assert pending["id"] == b["id"]
    assert pending["public_name"] is None and pending["headline"] is None
    assert mutate(admin, "PATCH", queue + "/" + b["id"],
                  {"expected_version": b["version"], "decision": "approve"}).status_code == 409
    profile = approve(admin, submit(first, draft))
    assert visitor.get(public_url).json()["entries"][0]["id"] == a["id"]
    b = approve_portfolio(admin, b)
    assert len(visitor.get(public_url).json()["entries"]) == 2
    response = mutate(first, "DELETE", "/api/community/profile/publication",
                      {"expected_version": profile["version"]})
    assert response.status_code == 200, response.text
    assert visitor.get(public_url).status_code == 404
    entries = first.get(url).json()["entries"]
    assert {entry["status"] for entry in entries} == {"hidden"}
    assert all(entry["consent_at"] is None for entry in entries)
    profile = approve(admin, submit(first, response.json()["profile"]))
    assert visitor.get(public_url).json()["entries"] == []
    a = next(entry for entry in entries if entry["id"] == a["id"])
    a = approve_portfolio(admin, submit_portfolio(first, a))
    assert len(visitor.get(public_url).json()["entries"]) == 1
    request = mutate(first, "POST", "/api/account/privacy-requests", {"kind": "deletion"})
    assert request.status_code == 201, request.text
    assert visitor.get(public_url).status_code == 404
    assert first.get(url).status_code == 403
    from app.privacy_disposal import impact_preview
    with database(app.state.db_path) as db:
        row = db.execute("SELECT request_key FROM privacy_rights_requests WHERE user_id=?",
                         (ids["first"],)).fetchone()
        preview = impact_preview(db, row["request_key"])
        assert preview["counts"]["community_portfolio_entries"] == 2
        assert preview["automatic_deletion"] is False


def reputation_payload(connection_id, **changes):
    return {"connection_id": connection_id, "client_key": str(uuid4()),
            "skill": "Обучение команды", "context": "Совместно готовили обучение новых сотрудников",
            "body": "Коллега понятно объясняет процессы и помогает закреплять знания.",
            "publish_consent": True, **changes}


def offer_reputation(client, connection_id, **changes):
    result = mutate(client, "POST", "/api/community/reputation", reputation_payload(connection_id, **changes))
    assert result.status_code == 200, result.text
    return result.json()["entry"]


def accept_reputation(client, entry):
    result = mutate(client, "POST", "/api/community/reputation/" + entry["id"] + "/respond",
                    {"expected_version": entry["version"], "decision": "accept", "publish_consent": True})
    assert result.status_code == 200, result.text
    return result.json()["entry"]


def approve_reputation(admin, entry):
    result = mutate(admin, "PATCH", "/api/admin/community/reputation/" + entry["id"],
                    {"expected_version": entry["version"], "decision": "approve"})
    assert result.status_code == 200, result.text
    return result.json()["entry"]


def test_reputation_requires_accepted_connection_two_consents_and_moderation(community):
    app, clients, ids = community
    first, second, outsider, admin, visitor = (
        clients[key] for key in ("first", "second", "outsider", "admin", "visitor"))
    a = publish(clients, "first", public_name="Автор рекомендации")
    b = publish(clients, "second", public_name="Коллега по проекту")
    publish(clients, "outsider")
    url = "/api/community/reputation"
    queue = "/api/admin/community/reputation"
    public = "/api/community/people/" + b["public_id"] + "/reputation"
    page = "/people/" + b["public_id"]
    connection = connect(clients, b["public_id"])
    cid = connection["id"]
    payload = reputation_payload(cid, body="Работает внимательно. <img src=x onerror=window.reputationXss=1>")
    assert visitor.get(url).status_code == 401
    assert clients["employer"].get(url).status_code == 403
    assert outsider.get(queue).status_code == 403
    assert mutate(first, "POST", url, payload).status_code == 409
    assert mutate(second, "POST", "/api/community/connections/" + cid + "/respond",
                  {"decision": "accept"}).status_code == 200
    assert mutate(outsider, "POST", url, payload).status_code == 404
    assert mutate(first, "POST", url, {**payload, "publish_consent": False}).status_code == 400
    assert mutate(first, "POST", url, {**payload, "publish_consent": "true"}).status_code == 422
    assert mutate(first, "POST", url, {**payload, "body": "Позвоните мне по номеру +79991234567"}).status_code == 422
    response = mutate(first, "POST", url, payload)
    assert response.status_code == 200, response.text
    offer = response.json()["entry"]
    assert offer["status"] == "offered"
    assert mutate(first, "POST", url, payload).json()["entry"] == offer
    assert mutate(first, "POST", url, reputation_payload(cid)).status_code == 409
    assert outsider.get(url).json()["entries"] == []
    assert second.get(url).json()["entries"][0]["id"] == offer["id"]
    assert first.get(url + "?direction=outgoing").json()["entries"][0]["id"] == offer["id"]
    assert admin.get(queue).json()["entries"] == []
    assert visitor.get(public).json()["entries"] == []
    assert offer["skill"] not in visitor.get(page).text
    decision = {"expected_version": offer["version"], "decision": "accept", "publish_consent": True}
    path = url + "/" + offer["id"]
    assert mutate(first, "POST", path + "/respond", decision).status_code == 403
    assert mutate(outsider, "POST", path + "/respond", decision).status_code == 404
    assert mutate(second, "POST", path + "/respond", {**decision, "publish_consent": False}).status_code == 400
    assert mutate(admin, "PATCH", queue + "/" + offer["id"],
                  {"expected_version": offer["version"], "decision": "approve"}).status_code == 409
    pending = accept_reputation(second, offer)
    assert pending["status"] == "pending"
    assert visitor.get(public).json()["entries"] == []
    assert admin.get(queue).json()["entries"][0]["id"] == offer["id"]
    approved = approve_reputation(admin, pending)
    result = visitor.get(public)
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    entry = result.json()["entries"][0]
    assert set(entry) == {"id", "skill", "context", "body", "author_public_id", "author_public_name"}
    assert entry["author_public_id"] == a["public_id"]
    html = visitor.get(page).text
    assert offer["skill"] in html and "&lt;img" in html
    assert "<img src=x onerror=window.reputationXss=1>" not in html
    assert "first@community.example.invalid" not in html
    assert first.get("/api/account/data-export").json()["sections"]["my_written_recommendations"][0]["id"] == offer["id"]
    assert second.get("/api/account/data-export").json()["sections"]["my_received_recommendations"][0]["id"] == offer["id"]
    assert outsider.get("/api/account/data-export").json()["sections"]["my_received_recommendations"] == []
    assert mutate(outsider, "DELETE", path + "/publication",
                  {"expected_version": approved["version"]}).status_code == 404
    assert mutate(first, "DELETE", path + "/publication",
                  {"expected_version": offer["version"]}).status_code == 409
    withdrawn = mutate(first, "DELETE", path + "/publication", {"expected_version": approved["version"]})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["entry"]["status"] == "hidden"
    assert visitor.get(public).json()["entries"] == []
    assert mutate(first, "POST", url, reputation_payload(cid)).status_code == 409
    assert visitor.get(page).status_code == 200


def test_reputation_decline_revision_block_and_profile_privacy(community):
    app, clients, ids = community
    first, second, outsider, admin, visitor = (
        clients[key] for key in ("first", "second", "outsider", "admin", "visitor"))
    a = publish(clients, "first", public_name="Автор первой рекомендации")
    b = publish(clients, "second", public_name="Коллега по обмену опытом")
    c = publish(clients, "outsider")
    url = "/api/community/reputation"
    queue = "/api/admin/community/reputation"
    public = "/api/community/people/" + b["public_id"] + "/reputation"
    cid = connect(clients, b["public_id"])["id"]
    assert mutate(second, "POST", "/api/community/connections/" + cid + "/respond",
                  {"decision": "accept"}).status_code == 200
    offered = offer_reputation(first, cid)
    pending = accept_reputation(second, offered)
    rejected = mutate(admin, "PATCH", queue + "/" + pending["id"],
                      {"expected_version": pending["version"], "decision": "reject",
                       "reason": "Уточните описание совместной работы"})
    assert rejected.status_code == 200, rejected.text
    revised = offer_reputation(first, cid, skill="Организация обучения")
    assert revised["id"] == offered["id"] and revised["status"] == "offered"
    assert revised["recipient_consent_at"] is None
    approved = approve_reputation(admin, accept_reputation(second, revised))
    reverse = offer_reputation(second, cid)
    declined = mutate(first, "POST", url + "/" + reverse["id"] + "/respond",
                      {"expected_version": reverse["version"], "decision": "decline"})
    assert declined.status_code == 200, declined.text
    assert mutate(second, "POST", url, reputation_payload(cid)).status_code == 409
    draft = save(first, public_name="Непубличное имя черновика")
    assert visitor.get(public).json()["entries"] == []
    assert second.get(url).json()["entries"][0]["counterpart_public_name"] is None
    assert admin.get(queue + "?status=published").json()["entries"] == []
    a = approve(admin, submit(first, draft))
    assert visitor.get(public).json()["entries"][0]["id"] == approved["id"]
    assert mutate(second, "POST", "/api/community/connections/" + cid + "/block").status_code == 200
    assert visitor.get(public).json()["entries"] == []
    assert second.get(url).json()["entries"][0]["status"] == "hidden"
    other = connect(clients, c["public_id"])["id"]
    assert mutate(outsider, "POST", "/api/community/connections/" + other + "/respond",
                  {"decision": "accept"}).status_code == 200
    second_record = approve_reputation(admin, accept_reputation(outsider, offer_reputation(first, other)))
    other_public = "/api/community/people/" + c["public_id"] + "/reputation"
    assert visitor.get(other_public).json()["entries"][0]["id"] == second_record["id"]
    withdrawn = mutate(first, "DELETE", "/api/community/profile/publication",
                       {"expected_version": a["version"]})
    assert withdrawn.status_code == 200, withdrawn.text
    assert visitor.get(other_public).json()["entries"] == []
    assert outsider.get(url).json()["entries"][0]["status"] == "hidden"
    a = approve(admin, submit(first, withdrawn.json()["profile"]))
    assert visitor.get(other_public).json()["entries"] == []
    request = mutate(first, "POST", "/api/account/privacy-requests", {"kind": "deletion"})
    assert request.status_code == 201, request.text
    assert first.get(url).status_code == 403
    from app.privacy_disposal import impact_preview
    with database(app.state.db_path) as db:
        row = db.execute("SELECT request_key FROM privacy_rights_requests WHERE user_id=?",
                         (ids["first"],)).fetchone()
        preview = impact_preview(db, row["request_key"])
        assert preview["counts"]["community_recommendations"] == 3
        assert preview["automatic_deletion"] is False

