"""Capture screenshot evidence for PR review, using only isolated fictional data."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8768"
HEADERS = {"X-Requested-With": "OPYT50"}
OUTPUT = Path(os.environ.get("STAZHNO_VISUAL_REVIEW_DIR", "visual-review"))


def login(page, email):
    response = page.request.post(
        URL + "/api/login", headers=HEADERS,
        data={"email": email, "password": "DemoPass2026!"},
    )
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")
    expect(page.locator("#dashboard")).to_be_visible()


def logout(page):
    response = page.request.post(URL + "/api/logout", headers=HEADERS)
    assert response.status == 200, response.text()


def make_invitation(page):
    login(page, "company@demo.example")
    vacancies = page.request.get(URL + "/api/employer/vacancies")
    assert vacancies.status == 200, vacancies.text()
    vacancy_id = next(
        vacancy["id"] for vacancy in vacancies.json()["jobs"]
        if vacancy["title"] == "Кладовщик"
    )
    matches = page.request.get(URL + f"/api/employer/vacancies/{vacancy_id}/matches")
    assert matches.status == 200, matches.text()
    candidate_id = next(
        candidate["candidate_id"] for candidate in matches.json()["matches"]
        if candidate["profession"] == "Кладовщик"
    )
    invitation = page.request.post(
        URL + "/api/employer/invitations", headers=HEADERS,
        data={"vacancy_id": vacancy_id, "candidate_id": candidate_id},
    )
    assert invitation.status == 201, invitation.text()
    logout(page)


def capture(page, name, width, height, selector=None):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_load_state("networkidle")
    if selector:
        expect(page.locator(selector)).to_be_visible()
        page.locator(selector).screenshot(path=str(OUTPUT / (name + ".png")))
    else:
        page.screenshot(path=str(OUTPUT / (name + ".png")), full_page=True)
    # A carousel or horizontal sub-navigation may scroll inside itself,
    # but the document must not force users to scroll sideways.
    widths = page.evaluate("""() => ({
        viewport: document.documentElement.clientWidth,
        document: document.documentElement.scrollWidth
    })""")
    assert widths["document"] <= widths["viewport"] + 3, (
        f"{name}: document horizontal overflow {widths}"
    )
    print(f"Captured {name}: {width}x{height}")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stazhno-visual-") as temp:
        env = dict(
            os.environ,
            OPYT50_DB_PATH=str(Path(temp) / "demo.db"),
            OPYT50_PREVIEW_SEED_DEMO="0",
            OPYT50_COOKIE_SECURE="0",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT, env=env, check=True, capture_output=True,
        )
        server_log = (Path(temp) / "server.log").open("w", encoding="utf-8")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8768"],
            cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
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
                raise RuntimeError("Visual review test server unavailable")

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, args=["--no-sandbox"]
                )
                try:
                    context = browser.new_context(
                        viewport={"width": 1366, "height": 900}, locale="ru-RU"
                    )
                    page = context.new_page()

                    page.goto(URL, wait_until="networkidle")
                    for label, width, height in (
                        ("desktop", 1366, 900),
                        ("tablet", 820, 1024),
                        ("mobile", 390, 844),
                    ):
                        capture(page, f"01-public-{label}", width, height)

                    make_invitation(page)
                    login(page, "kladovshik@demo.example")
                    expect(page.locator(".overview-priority h3")).to_have_text(
                        "Ответьте на приглашение работодателя"
                    )
                    for label, width, height in (
                        ("desktop", 1366, 900),
                        ("tablet", 820, 1024),
                        ("mobile", 390, 844),
                    ):
                        capture(page, f"02-candidate-{label}", width, height, "#dashboard")

                    page.locator(".overview-priority [data-action='open-candidate-invitations']").click()
                    expect(page.locator("#dashboard-main")).to_contain_text("Знакомства")
                    capture(page, "03-candidate-invitations-mobile", 390, 844, "#dashboard")

                    logout(page)
                    login(page, "company@demo.example")
                    for label, width, height in (
                        ("desktop", 1366, 900),
                        ("tablet", 820, 1024),
                        ("mobile", 390, 844),
                    ):
                        capture(page, f"04-employer-{label}", width, height, "#dashboard")
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
            server_log.close()

    print("PR visual review screenshots captured from fictional local data")


if __name__ == "__main__":
    main()
