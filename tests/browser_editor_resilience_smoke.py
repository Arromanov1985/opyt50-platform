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
    expect(page.locator("#company-about")).to_have_value(
        "Вымышленная компания. Проверка сохранения при ошибке 503."
    )

    # Existing preview gate must still be required for vacancy publication.
    page.locator("[data-dashboard-tab-select]").select_option("create")
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
    expect(page.locator("#dashboard-main")).to_contain_text(title)
    jobs = page.request.get(URL + "/api/employer/vacancies").json()["jobs"]
    assert sum(job["title"] == title for job in jobs) == 1

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
