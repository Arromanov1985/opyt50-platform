"""Browser smoke for structured reports and the admin safety center."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8766"
HEADERS = {"X-Requested-With": "OPYT50"}


def api_login(page, email, password="DemoPass2026!"):
    response = page.request.post(
        URL + "/api/login",
        headers=HEADERS,
        data={"email": email, "password": password},
    )
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")


def api_logout(page):
    response = page.request.post(URL + "/api/logout", headers=HEADERS)
    assert response.status == 200, response.text()


def run_browser(page):
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    page.goto(URL, wait_until="networkidle")
    api_login(page, "kladovshik@demo.example")

    jobs = page.request.get(URL + "/api/jobs").json()["jobs"]
    job = next(item for item in jobs if item["title"] == "Кладовщик")
    vacancy_id = job["id"]

    page.locator("#profession-filter").fill("Кладовщик")
    page.locator("#jobs-filter").click()
    card = page.locator(f"#public-jobs [data-job-id='{vacancy_id}']")
    expect(card).to_be_visible()
    card.locator("[data-v02-action='details']").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    page.locator("#job-dialog [data-v02-action='report']").click()

    expect(page.locator("#report-dialog")).to_be_visible()
    expect(page.locator("#report-dialog-title")).to_have_text("Сообщить о проблеме")
    expect(page.locator(".report-choice")).to_have_count(2)
    expect(page.locator("#report-reason")).to_be_visible()
    expect(page.locator("#report-details")).to_be_visible()
    page.locator("#report-reason").select_option("misleading")
    page.locator("#report-details").fill("Условия вакансии требуют дополнительной проверки.")
    expect(page.locator("#report-details-count")).to_contain_text("50 / 800")
    with page.expect_response(lambda response: (
        response.url.endswith("/api/reports") and response.request.method == "POST"
    )) as first_report:
        page.locator("#report-submit").click()
    assert first_report.value.status == 201, first_report.value.text()
    expect(page.locator("#report-success")).to_be_visible()
    expect(page.locator("#report-success")).to_contain_text("Жалоба отправлена")
    page.locator("#report-success-close").click()
    expect(page.locator("#report-dialog")).not_to_be_visible()

    api_logout(page)

    second_email = "safety-second@example.test"
    password = "SafetyTest2026!"
    registered = page.request.post(
        URL + "/api/register",
        headers=HEADERS,
        data={
            "role": "candidate",
            "name": "Второй тестовый кандидат",
            "email": second_email,
            "password": password,
        },
    )
    assert registered.status == 201, registered.text()
    second_report = page.request.post(
        URL + "/api/reports",
        headers=HEADERS,
        data={
            "vacancy_id": vacancy_id,
            "target_type": "vacancy",
            "reason": "fraud",
            "details": "Второй независимый сигнал для проверки модерации.",
        },
    )
    assert second_report.status == 201, second_report.text()
    assert second_report.json()["vacancy_pending_review"] is True
    assert page.request.get(URL + f"/api/jobs/{vacancy_id}").status == 404

    api_logout(page)
    api_login(page, "admin@demo.example")
    expect(page.locator("[data-v02-action='admin-reports']")).to_be_visible()
    page.locator("[data-v02-action='admin-reports']").first.click()

    center = page.locator("#admin-v02-results")
    expect(center).to_contain_text("Центр безопасности")
    expect(center).to_contain_text("Новые жалобы")
    expect(center).to_contain_text("Вакансии на проверке")

    page.locator("[data-v02-action='admin-safety-filter'][data-filter='pending']").first.click()
    expect(center).to_contain_text("Кладовщик")
    expect(center.locator(f"[data-moderation-reason='{vacancy_id}']")).to_be_visible()
    with page.expect_response(lambda response: (
        response.url.endswith(f"/api/admin/vacancies/{vacancy_id}/moderation") and
        response.request.method == "PATCH"
    )) as approved:
        center.locator(
            f"[data-v02-action='admin-moderation'][data-id='{vacancy_id}'][data-status='approved']"
        ).click()
    assert approved.value.status == 200, approved.value.text()
    expect(center).to_contain_text("Нет вакансий, ожидающих проверки")
    assert page.request.get(URL + f"/api/jobs/{vacancy_id}").status == 200

    page.locator("[data-v02-action='admin-safety-filter'][data-filter='new']").first.click()
    expect(center.locator("[data-v02-action='admin-report-status'][data-status='reviewed']").first).to_be_visible()
    with page.expect_response(lambda response: (
        "/api/admin/reports/" in response.url and response.url.endswith("/status") and
        response.request.method == "PATCH"
    )) as reviewed:
        center.locator("[data-v02-action='admin-report-status'][data-status='reviewed']").first.click()
    assert reviewed.value.status == 200, reviewed.value.text()

    page.locator("[data-v02-action='admin-safety-filter'][data-filter='reviewed']").first.click()
    expect(center).to_contain_text("В работе")
    expect(center).to_contain_text("Кладовщик")

    if browser_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(browser_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-safety-smoke-") as tmp:
        env = dict(
            os.environ,
            OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
            OPYT50_PREVIEW_SEED_DEMO="0",
            OPYT50_COOKIE_SECURE="0",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        server_log_path = Path(tmp) / "uvicorn.log"
        server_log = server_log_path.open("w", encoding="utf-8")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8766",
            ],
            cwd=ROOT,
            env=env,
            stdout=server_log,
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
                        run_browser(page)
                    except Exception:
                        page.screenshot(path=str(Path(tmp) / "failure.png"), full_page=True)
                        server_log.flush()
                        print(
                            "Uvicorn server error log:\n"
                            + server_log_path.read_text(encoding="utf-8")[-12000:],
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
                server_log.close()

    print("Browser safety smoke: report form, auto-hide, safety center and moderation PASSED")


if __name__ == "__main__":
    main()
