"""Draft-loss and interrupted-save regression, using local fictional accounts."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8772"
HEADERS = {"X-Requested-With": "OPYT50"}


def login(page, email):
    response = page.request.post(
        URL + "/api/login", headers=HEADERS,
        data={"email": email, "password": "DemoPass2026!"},
    )
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")
    expect(page.locator("#dashboard")).to_be_visible()


def exercise_forms(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    login(page, "kladovshik@demo.example")
    page.locator(".dashboard-tabs [data-tab='profile']").click()
    profession = page.locator("#profile-profession")
    previous = profession.input_value()
    profession.fill("Контролёр склада — локальный тест")
    expect(page.locator("#profile-form .editor-save-status")).to_contain_text(
        "Есть несохранённые изменения"
    )
    assert profession.input_value() != previous

    # On a phone, dismissing the leave warning retains all form data.
    page.set_viewport_size({"width": 390, "height": 844})
    prompts = []
    page.once("dialog", lambda d: (prompts.append(d.message), d.dismiss()))
    page.locator("[data-dashboard-tab-select]").select_option("applications")
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("profile")
    expect(profession).to_have_value("Контролёр склада — локальный тест")
    assert len(prompts) == 1 and "несохранённые" in prompts[0]
    assert page.evaluate("""() => {
      const e = new Event('beforeunload', {cancelable:true});
      window.dispatchEvent(e);
      return e.defaultPrevented;
    }"""), "Page reload must also warn on unsaved changes"

    # A refused request must keep the fields and allow a deliberate retry.
    def lost_network(route):
        route.abort("failed")
    page.route("**/api/candidate/profile", lost_network)
    page.locator("#profile-form button[type='submit']").click()
    expect(page.locator("#profile-form .editor-save-status")).to_contain_text(
        "Соединение прервалось"
    )
    expect(profession).to_have_value("Контролёр склада — локальный тест")
    expect(page.locator("#profile-form button[type='submit']")).to_be_enabled()
    assert page.evaluate(
        "() => !document.querySelector('#profile-form').inert"
    )
    page.unroute("**/api/candidate/profile", lost_network)
    with page.expect_response(lambda r: (
        r.url.endswith("/api/candidate/profile") and r.request.method == "PUT"
    )) as saved:
        page.locator("#profile-form button[type='submit']").click()
    assert saved.value.status == 200
    expect(page.locator("#profile-form .editor-save-status")).to_have_text(
        "Изменения сохранены."
    )
    # A successful HTTP response can precede the final async session refresh.
    # Do not navigate while the form is still inert/busy.
    expect(page.locator("#profile-form")).not_to_have_attribute("inert", "")
    # The saved form may be left without a leave dialog.
    page.locator("[data-dashboard-tab-select]").select_option("applications")
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("applications")
    profile = page.request.get(URL + "/api/me").json()["user"]["profile"]
    assert profile["profession"] == "Контролёр склада — локальный тест"

    # A temporary /api/me outage must not falsely clear a valid session.
    def session_outage(route):
        route.fulfill(status=503, content_type="application/json",
                      body='{"detail":"Сервис временно недоступен"}')
    page.route("**/api/me", session_outage)
    page.locator("[data-dashboard-tab-select]").select_option("offers")
    expect(page.locator("#dashboard")).to_be_visible()
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("offers")
    page.unroute("**/api/me", session_outage)

    assert page.request.post(URL + "/api/logout", headers=HEADERS).status == 200
    login(page, "company@demo.example")
    page.locator("[data-dashboard-tab-select]").select_option("company")
    about = page.locator("#company-about")
    about.fill("Вымышленная компания. Проверка сохранения при ошибке 503.")
    expect(page.locator("#company-form .editor-save-status")).to_contain_text(
        "Есть несохранённые изменения"
    )

    # HTTP failure leaves the company editor editable, never clears it.
    def service_unavailable(route):
        if route.request.method == "PUT":
            route.fulfill(
                status=503, content_type="application/json",
                body='{"detail":"Сервис временно недоступен"}',
            )
        else:
            route.continue_()
    page.route("**/api/employer/company", service_unavailable)
    page.locator("#company-form button[type='submit']").click()
    expect(page.locator("#company-form .editor-save-status")).to_contain_text(
        "Сервис временно недоступен"
    )
    expect(about).to_have_value(
        "Вымышленная компания. Проверка сохранения при ошибке 503."
    )
    expect(page.locator("#company-form button[type='submit']")).to_be_enabled()
    page.unroute("**/api/employer/company", service_unavailable)
    with page.expect_response(lambda r: (
        r.url.endswith("/api/employer/company") and r.request.method == "PUT"
    )) as saved_company:
        page.locator("#company-form button[type='submit']").click()
    assert saved_company.value.status == 200
    expect(page.locator("#toast")).to_contain_text("Данные компании сохранены.")
    expect(page.locator("#company-form")).not_to_have_attribute("inert", "")
    expect(page.locator("#company-about")).to_have_value(
        "Вымышленная компания. Проверка сохранения при ошибке 503."
    )

    # Wait for the full post-save UI refresh before navigating.
    page.locator("[data-dashboard-tab-select]").select_option("create")
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    title = "Специалист по складу — проверка сохранения"
    page.locator("#vacancy-title").fill(title)
    page.locator("#vacancy-city").fill("Тестоград")
    page.locator("#vacancy-skills").fill("Склад, документы")
    page.locator("#vacancy-salary-min").fill("65000")
    page.locator("#vacancy-salary-max").fill("83000")
    page.locator("#vacancy-responsibilities").fill("Сверка документов и приёмка")
    page.locator("#vacancy-requirements").fill("Уверенная работа с документами")
    page.locator("#vacancy-conditions").fill("График 5/2, обучение")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-publish")).to_be_enabled()

    def fail_publish(route):
        if route.request.method == "POST":
            route.fulfill(
                status=503, content_type="application/json",
                body='{"detail":"Временно не можем опубликовать"}',
            )
        else:
            route.continue_()
    page.route("**/api/employer/vacancies", fail_publish)
    page.locator("#vacancy-publish").click()
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "Временно не можем опубликовать"
    )
    expect(page.locator("#vacancy-title")).to_have_value(title)
    expect(page.locator("#vacancy-publish")).to_be_enabled()
    page.unroute("**/api/employer/vacancies", fail_publish)

    # Two fast programmatic clicks must not send two requests while pending.
    sent = []
    page.on("request", lambda req: sent.append(req.url) if (
        req.url.endswith("/api/employer/vacancies") and req.method == "POST"
    ) else None)
    with page.expect_response(lambda r: (
        r.url.endswith("/api/employer/vacancies") and r.request.method == "POST"
    )) as created:
        page.evaluate("""() => {
          const button = document.querySelector('#vacancy-publish');
          button.click();
          button.click();
        }""")
    assert created.value.status == 201, created.value.text()
    assert len(sent) == 1, sent
    # The API response can arrive before the async dashboard transition.
    # Do not start another form while the prior one is still inert/saving.
    expect(page.locator("#vacancy-form")).to_have_count(0)
    expect(page.locator("#dashboard-main")).to_contain_text(title)
    jobs = page.request.get(URL + "/api/employer/vacancies").json()["jobs"]
    assert sum(job["title"] == title for job in jobs) == 1


    # New employer feature: a partial draft remains private and survives a tab reload.
    page.locator("[data-dashboard-tab-select]").select_option("create")
    expect(page.locator("#vacancy-form")).to_be_visible()
    draft_title = "Оператор склада — серверный черновик"
    page.locator("#vacancy-title").fill(draft_title)
    page.locator("#vacancy-city").fill("Тестоград")
    page.locator("#vacancy-salary-min").fill("51500")
    page.locator("#vacancy-salary-max").fill("75000")
    page.locator("#vacancy-schedule").select_option("Сменный")
    page.locator("[data-action='save-vacancy-draft']").click()
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "Черновик сохранён"
    )
    # Saving an incomplete draft must not silently enable publication.
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    drafts = page.request.get(URL + "/api/employer/vacancy-drafts").json()["drafts"]
    assert len(drafts) == 1
    draft_id = drafts[0]["id"]
    assert drafts[0]["fields"]["salary_min"] == "51500"
    assert draft_title not in [job["title"] for job in
                               page.request.get(URL + "/api/jobs").json()["jobs"]]

    # Only a user-created server draft is autosaved. Changes need no second click.
    expect(page.locator("[data-action='save-vacancy-draft']")).to_have_text("Сохранить сейчас")
    with page.expect_response(lambda r: (
        f"/api/employer/vacancy-drafts/{draft_id}" in r.url
        and r.request.method == "PUT" and r.status == 200
    ), timeout=15000):
        page.locator("#vacancy-salary-min").fill("52000")
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "Черновик сохранён на сервере", timeout=10000,
    )
    autosaved = page.request.get(URL + f"/api/employer/vacancy-drafts/{draft_id}")
    assert autosaved.status == 200, autosaved.text()
    assert autosaved.json()["fields"]["salary_min"] == "52000"
    assert autosaved.json()["version"] > drafts[0]["version"]

    # Two devices edited the same draft: the second save must stop with 409.
    # The user chooses the local city, while a server-only condition is merged.
    remote_fields = dict(autosaved.json()["fields"])
    remote_fields["city"] = "Город со второго устройства"
    remote_fields["conditions"] = "Условия со второго устройства"
    remote_save = page.request.put(
        URL + f"/api/employer/vacancy-drafts/{draft_id}",
        headers=HEADERS,
        data={"fields": remote_fields, "expected_version": autosaved.json()["version"]},
    )
    assert remote_save.status == 200, remote_save.text()
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancy-drafts/{draft_id}")
        and r.request.method == "PUT" and r.status == 409
    ), timeout=15000):
        page.locator("#vacancy-city").fill("Мой город")
    comparison = page.locator("[data-draft-conflict-panel]")
    expect(comparison).to_be_visible()
    expect(comparison).to_contain_text("Город со второго устройства")
    expect(comparison).to_contain_text("Мой город")
    expect(comparison).to_contain_text("Условия со второго устройства")
    expect(page.locator("#vacancy-city")).to_have_value("Мой город")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    assert page.request.get(URL + f"/api/employer/vacancy-drafts/{draft_id}").json()["fields"]["city"] == "Город со второго устройства"
    expect(comparison.locator('[data-draft-conflict-choice="city"]')).to_have_value("")

    # A new keystroke while reviewing invalidates the old selection snapshot;
    # comparison must refresh without losing text or writing to the server.
    comparison.locator('[data-draft-conflict-choice="city"]').select_option("local")
    page.locator("#vacancy-skills").fill("Новое локальное умение")
    comparison.locator('[data-action="apply-draft-conflict"]').click()
    expect(comparison.locator('[data-draft-conflict-choice="city"]')).to_have_value("")
    expect(page.locator("#vacancy-skills")).to_have_value("Новое локальное умение")
    comparison.locator('[data-draft-conflict-choice="city"]').select_option("local")
    # While reviewing, the other device writes again. The first confirm
    # must hit 409 and refresh the comparison, never overwrite that update.
    during_review = page.request.get(
        URL + f"/api/employer/vacancy-drafts/{draft_id}"
    ).json()
    concurrent_fields = dict(during_review["fields"])
    concurrent_fields["conditions"] = "Обновлённые серверные условия"
    concurrent = page.request.put(
        URL + f"/api/employer/vacancy-drafts/{draft_id}",
        headers=HEADERS,
        data={"fields": concurrent_fields, "expected_version": during_review["version"]},
    )
    assert concurrent.status == 200, concurrent.text()
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancy-drafts/{draft_id}")
        and r.request.method == "PUT" and r.status == 409
    ), timeout=15000):
        comparison.locator('[data-action="apply-draft-conflict"]').click()
    expect(comparison).to_contain_text("Обновлённые серверные условия")
    expect(comparison.locator('[data-draft-conflict-choice="city"]')).to_have_value("")
    comparison.locator('[data-draft-conflict-choice="city"]').select_option("local")
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancy-drafts/{draft_id}")
        and r.request.method == "PUT" and r.status == 200
    ), timeout=15000):
        comparison.locator('[data-action="apply-draft-conflict"]').click()
    expect(page.locator("[data-draft-conflict-panel]")).to_have_count(0)
    expect(page.locator("#vacancy-city")).to_have_value("Мой город")
    expect(page.locator("#vacancy-conditions")).to_have_value("Обновлённые серверные условия")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    merged = page.request.get(URL + f"/api/employer/vacancy-drafts/{draft_id}").json()
    assert merged["fields"]["city"] == "Мой город"
    assert merged["fields"]["conditions"] == "Обновлённые серверные условия"
    assert merged["fields"]["skills"] == "Новое локальное умение"

    # A different overlapping field can be resolved in favor of the server.
    remote_again = dict(merged["fields"])
    remote_again["requirements"] = "Требования сервера"
    updated_again = page.request.put(
        URL + f"/api/employer/vacancy-drafts/{draft_id}",
        headers=HEADERS,
        data={"fields": remote_again, "expected_version": merged["version"]},
    )
    assert updated_again.status == 200, updated_again.text()
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancy-drafts/{draft_id}")
        and r.request.method == "PUT" and r.status == 409
    ), timeout=15000):
        page.locator("#vacancy-requirements").fill("Мои требования")
    expect(comparison).to_be_visible()
    expect(comparison.locator('[data-draft-conflict-choice="requirements"]')).to_have_value("")
    comparison.locator('[data-draft-conflict-choice="requirements"]').select_option("server")
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancy-drafts/{draft_id}")
        and r.request.method == "PUT" and r.status == 200
    ), timeout=15000):
        comparison.locator('[data-action="apply-draft-conflict"]').click()
    expect(page.locator("#vacancy-requirements")).to_have_value("Требования сервера")
    assert page.request.get(URL + f"/api/employer/vacancy-drafts/{draft_id}").json()["fields"]["requirements"] == "Требования сервера"

    # A failed autosave stops retries, preserves the form and allows manual recovery.
    def draft_outage(route):
        if route.request.method == "PUT":
            route.fulfill(
                status=503, content_type="application/json",
                body='{"detail":"Временно недоступно"}',
            )
        else:
            route.continue_()
    page.route("**/api/employer/vacancy-drafts/*", draft_outage)
    with page.expect_response(lambda r: (
        f"/api/employer/vacancy-drafts/{draft_id}" in r.url
        and r.request.method == "PUT" and r.status == 503
    ), timeout=15000):
        page.locator("#vacancy-city").fill("Тестополис")
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "автосохранение остановлено", timeout=10000,
    )
    expect(page.locator("#vacancy-city")).to_have_value("Тестополис")
    page.unroute("**/api/employer/vacancy-drafts/*", draft_outage)
    page.locator("[data-action='save-vacancy-draft']").click()
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "Черновик сохранён на сервере",
    )
    assert page.request.get(
        URL + f"/api/employer/vacancy-drafts/{draft_id}"
    ).json()["fields"]["city"] == "Тестополис"

    # New overview reminder: employer can resume the latest private draft
    # without hunting for it in "My vacancies", including at 390 px.
    expect(page.locator("#vacancy-form")).not_to_have_attribute("inert", "")
    page.locator("[data-dashboard-tab-select]").select_option("overview")
    reminder = page.locator(".employer-draft-reminder")
    expect(reminder).to_be_visible()
    expect(reminder).to_contain_text(draft_title)
    expect(reminder).to_contain_text("Черновики: 1")
    reminder.locator("[data-action='resume-vacancy-draft']").click()
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-title")).to_have_value(draft_title)
    expect(page.locator("#vacancy-salary-min")).to_have_value("52000")
    page.locator("[data-dashboard-tab-select]").select_option("vacancies")
    expect(page.locator("#dashboard-main")).to_contain_text(draft_title)
    # Remote conditions and requirements were explicitly reconciled above.
    expect(page.locator(".employer-draft-progress")).to_contain_text("6 из 7")
    expect(page.locator(".employer-draft-card")).to_contain_text("Последнее сохранение")
    assert page.evaluate("() => draftSavedAt('2026-11-17 09:00:00+00') !== 'время не указано'")
    assert page.evaluate("() => draftSavedAt('2026-11-17 09:00:00') !== 'время не указано'")
    page.reload(wait_until="networkidle")
    expect(page.locator("#dashboard")).to_be_visible()
    page.locator("[data-dashboard-tab-select]").select_option("vacancies")
    page.locator(
        f"[data-action='resume-vacancy-draft'][data-id='{draft_id}']"
    ).click()
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-title")).to_have_value(draft_title)
    expect(page.locator("#vacancy-salary-min")).to_have_value("52000")
    expect(page.locator("#vacancy-city")).to_have_value("Тестополис")
    expect(page.locator("#vacancy-salary-max")).to_have_value("75000")
    expect(page.locator("#vacancy-schedule")).to_have_value("Сменный")
    page.locator("#vacancy-responsibilities").fill("Приём и учёт товаров")
    page.locator("#vacancy-requirements").fill("Навыки складского учёта")
    page.locator("#vacancy-conditions").fill("График 2/2, обучение")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-publish")).to_be_enabled()
    page.locator("#vacancy-publish").click()
    # Wait for the actual UI transition: the draft title is already visible
    # inside the editor, so an immediate text assertion would race publication.
    expect(page.locator("#vacancy-form")).to_have_count(0)
    expect(page.locator("#dashboard-main")).to_contain_text(draft_title)
    retry = page.request.post(
        URL + f"/api/employer/vacancy-drafts/{draft_id}/publish",
        headers=HEADERS,
    )
    assert retry.status == 200, retry.text()
    assert retry.json()["already_published"]
    published_jobs = page.request.get(URL + "/api/employer/vacancies").json()["jobs"]
    assert sum(job["title"] == draft_title for job in published_jobs) == 1
    assert page.request.get(URL + "/api/employer/vacancy-drafts").json()["drafts"] == []

    # Initial create: the server commits, but the browser loses the HTTP reply.
    # Repeating save with the SAME key must not create a second draft even if
    # the user has edited more fields before the retry.
    page.locator("[data-dashboard-tab-select]").select_option("create")
    expect(page.locator("#vacancy-form")).to_be_visible()
    first_title = "Оператор доставки — первый запрос потерял ответ"
    page.locator("#vacancy-title").fill(first_title)
    page.locator("#vacancy-city").fill("Подольск")
    received_keys = []

    def lose_first_draft_reply(route):
        if route.request.method == "POST":
            payload = json.loads(route.request.post_data or "{}")
            assert payload["request_key"]
            received_keys.append(payload["request_key"])
            response = route.fetch()
            assert response.status == 201, response.text()
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/api/employer/vacancy-drafts", lose_first_draft_reply)
    page.locator("[data-action='save-vacancy-draft']").click()
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "дубликат не создастся", timeout=10000,
    )
    expect(page.locator("#vacancy-title")).to_have_value(first_title)
    assert len(received_keys) == 1
    initially_created = page.request.get(URL + "/api/employer/vacancy-drafts").json()["drafts"]
    assert len(initially_created) == 1
    created_id = initially_created[0]["id"]
    assert initially_created[0]["fields"]["city"] == "Подольск"
    page.unroute("**/api/employer/vacancy-drafts", lose_first_draft_reply)

    # Changing the form after the lost reply creates a 409 on the repeated
    # POST. The UI securely recovers the original draft, then saves via PUT.
    page.locator("#vacancy-city").fill("Новый Подольск")
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancy-drafts/{created_id}")
        and r.request.method == "PUT" and r.status == 200
    ), timeout=15000):
        page.locator("[data-action='save-vacancy-draft']").click()
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "Черновик сохранён на сервере", timeout=10000,
    )
    after_retry = page.request.get(URL + "/api/employer/vacancy-drafts").json()["drafts"]
    assert len(after_retry) == 1, after_retry
    assert after_retry[0]["id"] == created_id
    assert after_retry[0]["fields"]["city"] == "Новый Подольск"
    assert after_retry[0]["version"] == 2
    assert first_title not in [j["title"] for j in page.request.get(
        URL + "/api/jobs").json()["jobs"]]


    # Published vacancy edits: reconcile local and server changes without
    # creating a second job, losing the applicant trail or silently publishing.
    original_description = (
        "Обязанности:\\nУчёт товаров\\n\\nТребования:\\nЗнание 1С"
        "\\n\\nУсловия работы:\\nГрафик 2/2"
    )
    original_description = original_description.replace("\\n", "\n")
    published_payload = {
        "title": "Специалист отдела отгрузки",
        "city": "Подольск", "salary_min": 70000, "salary_max": 95000,
        "schedule": "Сменный", "employment": "Полная", "skills": "1С",
        "description": original_description,
    }
    created_job = page.request.post(
        URL + "/api/employer/vacancies", headers=HEADERS, data=published_payload,
    )
    assert created_job.status == 201, created_job.text()
    job_id = created_job.json()["id"]
    edit_url = URL + f"/api/employer/vacancies/{job_id}"
    original_job = page.request.get(edit_url).json()["job"]
    page.locator("[data-dashboard-tab-select]").select_option("vacancies")
    page.locator(f"[data-action='edit-job'][data-id='{job_id}']").click()
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-form")).to_have_attribute("data-edit-id", str(job_id))
    page.locator("#vacancy-city").fill("Тверь")
    page.locator("#vacancy-requirements").fill("Требования на компьютере")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-publish")).to_be_enabled()

    # The tablet updates the same city and independently changes conditions.
    server_description = original_description.replace(
        "График 2/2", "Сменный график 3/3",
    )
    remote_body = {
        **{field: original_job[field] for field in [
            "title","city","salary_min","salary_max","schedule",
            "employment","skills","description"
        ]},
        "city": "Москва", "description": server_description,
        "expected_revision": original_job["revision"],
    }
    remote = page.request.patch(edit_url, headers=HEADERS, data=remote_body)
    assert remote.status == 200, remote.text()
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancies/{job_id}")
        and r.request.method == "PATCH" and r.status == 409
    ), timeout=15000):
        page.locator("#vacancy-publish").click()
    comparison = page.locator("[data-published-conflict-panel]")
    expect(comparison).to_be_visible()
    expect(comparison).to_contain_text("Москва")
    expect(comparison).to_contain_text("Тверь")
    expect(comparison).to_contain_text("Сменный график 3/3")
    expect(comparison.locator('[data-published-conflict-choice="city"]')).to_have_value("")
    expect(comparison.locator('[data-published-conflict-choice="conditions"]')).to_have_value("server")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    assert page.request.get(edit_url).json()["job"]["city"] == "Москва"

    # If a new keystroke arrives during the review, selections must refresh.
    comparison.locator('[data-published-conflict-choice="city"]').select_option("local")
    page.locator("#vacancy-skills").fill("1С, новый локальный навык")
    comparison.locator('[data-action="apply-published-conflict"]').click()
    expect(comparison.locator('[data-published-conflict-choice="city"]')).to_have_value("")
    expect(page.locator("#vacancy-skills")).to_have_value("1С, новый локальный навык")

    # Another tablet edit during the comparison must not be overwritten.
    latest_job = page.request.get(edit_url).json()["job"]
    remote_again = {
        **{field: latest_job[field] for field in [
            "title","city","salary_min","salary_max","schedule",
            "employment","skills","description"
        ]},
        "description": server_description.replace("График 3/3", "График 4/4"),
        "expected_revision": latest_job["revision"],
    }
    remote_again["description"] = remote_again["description"].replace("Сменный график 3/3", "График 4/4")
    remotely_changed = page.request.patch(edit_url,headers=HEADERS,data=remote_again)
    assert remotely_changed.status == 200, remotely_changed.text()
    comparison.locator('[data-published-conflict-choice="city"]').select_option("local")
    comparison.locator('[data-action="apply-published-conflict"]').click()
    expect(comparison).to_contain_text("График 4/4")
    expect(comparison.locator('[data-published-conflict-choice="city"]')).to_have_value("")

    # Deliberately choose local city; preserve server-only conditions.
    comparison.locator('[data-published-conflict-choice="city"]').select_option("local")
    page.set_viewport_size({"width":390,"height":844})
    expect(comparison).to_be_visible()
    comparison.locator('[data-action="apply-published-conflict"]').click()
    expect(page.locator("[data-published-conflict-panel]")).to_have_count(0)
    expect(page.locator("#vacancy-city")).to_have_value("Тверь")
    expect(page.locator("#vacancy-requirements")).to_have_value("Требования на компьютере")
    expect(page.locator("#vacancy-conditions")).to_have_value("График 4/4")
    expect(page.locator("#vacancy-skills")).to_have_value("1С, новый локальный навык")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text("НЕ сохранены")
    # Nothing is published by applying comparison alone.
    assert page.request.get(edit_url).json()["job"]["city"] == "Москва"

    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-publish")).to_be_enabled()
    with page.expect_response(lambda r: (
        r.url.endswith(f"/api/employer/vacancies/{job_id}")
        and r.request.method == "PATCH" and r.status == 200
    ),timeout=15000):
        page.locator("#vacancy-publish").click()
    expect(page.locator("#vacancy-form")).to_have_count(0)
    saved_job = page.request.get(edit_url).json()["job"]
    assert saved_job["city"] == "Тверь"
    assert "Требования на компьютере" in saved_job["description"]
    assert "График 4/4" in saved_job["description"]
    assert saved_job["skills"] == "1С, новый локальный навык"
    assert saved_job["id"] == job_id
    assert saved_job["created_at"] == original_job["created_at"]
    assert sum(j["id"] == job_id for j in
               page.request.get(URL+"/api/employer/vacancies").json()["jobs"]) == 1
    page.set_viewport_size({"width":1280,"height":800})

    assert not errors, errors


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-editor-") as temp:
        db = str(Path(temp) / "demo.db")
        env = dict(
            os.environ, OPYT50_DB_PATH=db, OPYT50_PREVIEW_SEED_DEMO="0",
            OPYT50_COOKIE_SECURE="0", OPYT50_MAIL_WORKER_ENABLED="0",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", db],
            cwd=ROOT, env=env, check=True, capture_output=True,
        )
        log_path = Path(temp) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app",
                 "--host", "127.0.0.1", "--port", "8772"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(80):
                    try:
                        with urlopen(URL + "/api/health", timeout=1) as resp:
                            if resp.status == 200:
                                break
                    except Exception:
                        time.sleep(.25)
                else:
                    raise RuntimeError("Editor local test server unavailable")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        headless=True, args=["--no-sandbox"],
                    )
                    try:
                        context = browser.new_context(
                            viewport={"width": 1280, "height": 800},
                            locale="ru-RU",
                        )
                        try:
                            exercise_forms(context.new_page())
                        except Exception:
                            print(log_path.read_text(encoding="utf-8")[-10000:],
                                  file=sys.stderr)
                            raise
                        finally:
                            context.close()
                    finally:
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()

    print("Browser form resilience (mobile, network, HTTP 503, duplicate) PASSED")


if __name__ == "__main__":
    main()
