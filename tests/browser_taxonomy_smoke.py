"""Browser smoke for profession and skill taxonomy suggestions."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8768"
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


def run_taxonomy(page):
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    api_login(page, "kladovshik@demo.example")
    page.locator(".dashboard-tabs [data-tab='profile']").click()

    profession = page.locator("#profile-profession")
    expect(profession).to_be_visible()
    expect(profession).to_have_attribute("data-taxonomy-ready", "1")
    profession.fill("террит")
    suggestions = profession.locator("xpath=..").locator(".taxonomy-suggestions")
    expect(suggestions).to_be_visible()
    expect(suggestions).to_contain_text("Территориальный менеджер")
    profession.press("ArrowDown")
    profession.press("Enter")
    expect(profession).to_have_value("Территориальный менеджер")
    expect(profession.locator("xpath=..").locator(".taxonomy-context")).to_contain_text("региональные продажи")

    skills = page.locator("#profile-skills")
    skills.fill("Microsoft Ex")
    skill_suggestions = skills.locator("xpath=..").locator(".taxonomy-suggestions")
    expect(skill_suggestions).to_be_visible()
    expect(skill_suggestions).to_contain_text("Excel")
    skill_suggestions.locator(".taxonomy-option", has_text="Excel").first.click()
    expect(skills).to_have_value("Excel")
    expect(skills.locator("xpath=..").locator(".taxonomy-context")).to_contain_text("Excel")

    skills.fill("Excel, Bitrix")
    expect(skill_suggestions).to_be_visible()
    expect(skill_suggestions).to_contain_text("Битрикс24")
    skill_suggestions.locator(".taxonomy-option", has_text="Битрикс24").first.click()
    expect(skills).to_have_value("Excel, Битрикс24")
    expect(skills.locator("xpath=..").locator(".taxonomy-context")).to_contain_text("Excel")
    expect(skills.locator("xpath=..").locator(".taxonomy-context")).to_contain_text("Битрикс24")

    api_logout(page)
    api_login(page, "company@demo.example")
    page.locator(".dashboard-tabs [data-tab='create']").click()

    title = page.locator("#vacancy-title")
    expect(title).to_be_visible()
    expect(title).to_have_attribute("data-taxonomy-ready", "1")
    title.fill("террит")
    employer_prof_suggestions = title.locator("xpath=..").locator(".taxonomy-suggestions")
    expect(employer_prof_suggestions).to_be_visible()
    employer_prof_suggestions.locator(".taxonomy-option", has_text="Территориальный менеджер").first.click()
    expect(title).to_have_value("Территориальный менеджер")
    expect(title.locator("xpath=..").locator(".taxonomy-context")).to_contain_text("региональные продажи")

    vacancy_skills = page.locator("#vacancy-skills")
    vacancy_skills.fill("bitrix")
    employer_skill_suggestions = vacancy_skills.locator("xpath=..").locator(".taxonomy-suggestions")
    expect(employer_skill_suggestions).to_be_visible()
    employer_skill_suggestions.locator(".taxonomy-option", has_text="Битрикс24").first.click()
    expect(vacancy_skills).to_have_value("Битрикс24")
    expect(vacancy_skills.locator("xpath=..").locator(".taxonomy-context")).to_contain_text("Битрикс24")

    if browser_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(browser_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-taxonomy-smoke-") as tmp:
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
                "8768",
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
                        run_taxonomy(page)
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

    print("Browser taxonomy smoke: candidate and employer suggestions PASSED")


if __name__ == "__main__":
    main()
