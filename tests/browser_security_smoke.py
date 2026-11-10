"""Browser security smoke: stored XSS stays text in public surfaces."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8769"
HEADERS = {"X-Requested-With": "OPYT50"}


def login(page, email, password="DemoPass2026!"):
    response = page.request.post(
        URL + "/api/login",
        headers=HEADERS,
        data={"email": email, "password": password},
    )
    assert response.status == 200, response.text()


def logout(page):
    response = page.request.post(URL + "/api/logout", headers=HEADERS)
    assert response.status == 200, response.text()


def run_security(page):
    browser_errors = []
    dialogs = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    login(page, "company@demo.example")

    company = page.request.get(URL + "/api/employer/company").json()["company"]
    saved = page.request.put(
        URL + "/api/employer/company",
        headers=HEADERS,
        data={
            "company_name": company["company_name"],
            "inn": company.get("inn", ""),
            "about": '<img src=x onerror="window.__companyXss=1">Компания <b>безопасно</b>',
        },
    )
    assert saved.status == 200, saved.text()

    title = '<img src=x onerror="window.__jobXss=1"> Менеджер XSS'
    created = page.request.post(
        URL + "/api/employer/vacancies",
        headers=HEADERS,
        data={
            "title": title,
            "city": "Москва",
            "salary_min": 90000,
            "salary_max": 120000,
            "schedule": "Любой",
            "employment": "Любая",
            "skills": '<script>window.__skillXss=1</script>, Excel',
            "description": '<svg onload="window.__descriptionXss=1"></svg>Описание вакансии',
        },
    )
    assert created.status == 201, created.text()
    job_id = created.json()["id"]
    logout(page)

    page.goto(URL, wait_until="networkidle")
    card = page.locator(f"#public-jobs [data-job-id='{job_id}']")
    expect(card).to_be_visible()
    expect(card).to_contain_text("<img src=x")
    assert card.locator("script").count() == 0
    assert card.locator("svg").count() == 0
    assert card.locator("img[src='x']").count() == 0
    assert page.evaluate("typeof window.__jobXss") == "undefined"
    assert page.evaluate("typeof window.__skillXss") == "undefined"

    card.locator("[data-v02-action='details']").click()
    dialog = page.locator("#job-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("<svg onload=")
    assert dialog.locator("script").count() == 0
    assert dialog.locator("svg").count() == 0
    assert dialog.locator("img[src='x']").count() == 0
    assert page.evaluate("typeof window.__descriptionXss") == "undefined"

    dialog.locator("[data-v02-action='company']").click()
    company_dialog = page.locator("#company-dialog")
    expect(company_dialog).to_be_visible()
    expect(company_dialog).to_contain_text("<img src=x")
    assert company_dialog.locator("script").count() == 0
    assert company_dialog.locator("svg").count() == 0
    assert company_dialog.locator("img[src='x']").count() == 0
    assert page.evaluate("typeof window.__companyXss") == "undefined"

    # Administrator password alone must not create a session when MFA is enabled.
    if page.locator("#company-dialog").get_attribute("open") is not None:
        page.locator("#company-dialog-close").click()
    page.locator("#login-open").click()
    expect(page.locator("#auth-dialog")).to_be_visible()
    page.locator("#auth-email").fill("admin@demo.example")
    page.locator("#auth-password").fill("DemoPass2026!")
    with page.expect_response(lambda response: (
        response.url.endswith("/api/login") and response.request.method == "POST"
    )) as login_response:
        page.locator("#auth-submit").click()
    login_payload = login_response.value.json()
    assert login_payload["mfa_required"] is True
    assert login_payload["debug_code"].isdigit()
    expect(page.locator("#auth-mfa-panel")).to_be_visible()
    expect(page.locator("#auth-title")).to_have_text("Подтвердите вход")
    assert page.request.get(URL + "/api/me").status == 401

    page.locator("#auth-mfa-code").fill(login_payload["debug_code"])
    with page.expect_response(lambda response: (
        response.url.endswith("/api/admin/mfa/verify") and
        response.request.method == "POST"
    )) as verify_response:
        page.locator("#auth-submit").click()
    assert verify_response.value.status == 200, verify_response.value.text()
    expect(page.locator("#auth-dialog")).not_to_be_visible()
    expect(page.locator("#dashboard")).to_be_visible()
    expect(page.locator("#account-content")).to_contain_text("Администратор")
    assert page.request.get(URL + "/api/me").status == 200

    if dialogs:
        raise AssertionError("Unexpected browser dialogs: " + " | ".join(dialogs))
    if browser_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(browser_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-security-smoke-") as tmp:
        env = dict(
            os.environ,
            OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
            OPYT50_PREVIEW_SEED_DEMO="0",
            OPYT50_COOKIE_SECURE="0",
            OPYT50_ENV="development",
            OPYT50_ADMIN_MFA_MODE="email",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        log_path = Path(tmp) / "uvicorn.log"
        log = log_path.open("w", encoding="utf-8")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8769",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(80):
                try:
                    with urlopen(URL + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError("Local server did not become ready")

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    context = browser.new_context(viewport={"width": 1280, "height": 820}, locale="ru-RU")
                    page = context.new_page()
                    try:
                        run_security(page)
                    except Exception:
                        page.screenshot(path=str(Path(tmp) / "failure.png"), full_page=True)
                        log.flush()
                        print(
                            "Uvicorn server error log:\n"
                            + log_path.read_text(encoding="utf-8")[-12000:],
                            file=sys.stderr,
                        )
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
            finally:
                log.close()

    print("Browser security smoke: XSS escaping and admin MFA PASSED")


if __name__ == "__main__":
    main()
