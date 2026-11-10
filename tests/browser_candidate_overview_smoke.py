"""Browser smoke for the candidate career overview."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8767"
HEADERS = {"X-Requested-With": "OPYT50"}


def login(page, email, password="DemoPass2026!"):
    response = page.request.post(
        URL + "/api/login",
        headers=HEADERS,
        data={"email": email, "password": password},
    )
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")


def run_overview(page):
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    login(page, "kladovshik@demo.example")
    dashboard = page.locator("#dashboard-main")
    expect(dashboard).to_contain_text("ВАШ СЛЕДУЮЩИЙ ШАГ")
    expect(dashboard.locator(".overview-stat-card")).to_have_count(4)
    expect(dashboard.locator(".candidate-status-row")).to_be_visible()
    expect(dashboard.locator(".candidate-status-chip")).to_have_count(3)
    expect(dashboard.locator(".candidate-overview-grid")).to_be_visible()
    expect(dashboard).to_contain_text("Вакансии для вас")
    expect(dashboard).to_contain_text("Сейчас в процессе")
    expect(dashboard.locator(".candidate-overview-section")).to_have_count(2)

    # The overview must remain usable at the core mobile width.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(dashboard.locator(".candidate-overview-grid")).to_be_visible()
    expect(dashboard.locator(".candidate-status-row")).to_be_visible()
    expect(dashboard.locator(".candidate-status-chip").first).to_be_visible()

    # Navigation from the consolidated overview still uses the same real tabs.
    dashboard.locator("[data-tab='offers']").first.click()
    expect(dashboard).to_contain_text("Подходящие вакансии")
    page.locator(".dashboard-tabs [data-tab='overview']").click()
    expect(dashboard.locator(".candidate-overview-grid")).to_be_visible()

    if browser_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(browser_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-candidate-overview-") as tmp:
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
                "8767",
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
                        run_overview(page)
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

    print("Browser candidate overview smoke: desktop, mobile and tab navigation PASSED")


if __name__ == "__main__":
    main()
