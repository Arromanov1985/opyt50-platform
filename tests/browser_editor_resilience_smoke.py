"""Draft-loss and interrupted-save regression, using local fictional accounts."""
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
    drafts = page.request.get(URL + "/api/employer/vacancy-drafts").json()["drafts"]
    assert len(drafts) == 1
    draft_id = drafts[0]["id"]
    assert drafts[0]["fields"]["salary_min"] == "51500"
    assert draft_title not in [job["title"] for job in
                               page.request.get(URL + "/api/jobs").json()["jobs"]]

    # Only a user-created server draft is autosaved. Changes need no second click.
    expect(page.locator("[data-action='save-vacancy-draft']")).to_have_text("Сохранить сейчас")
    page.locator("#vacancy-salary-min").fill("52000")
    expect(page.locator("#vacancy-form .editor-save-status")).to_contain_text(
        "Черновик сохранён на сервере", timeout=10000,
    )
    autosaved = page.request.get(URL + f"/api/employer/vacancy-drafts/{draft_id}")
    assert autosaved.status == 200, autosaved.text()
    assert autosaved.json()["fields"]["salary_min"] == "52000"
    assert autosaved.json()["version"] > drafts[0]["version"]

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

    page.locator("[data-dashboard-tab-select]").select_option("vacancies")
    expect(page.locator("#dashboard-main")).to_contain_text(draft_title)
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
