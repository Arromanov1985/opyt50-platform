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


def reading_mode(page, enabled):
    button = page.locator("#reading-mode-toggle")
    expect(button).to_be_visible()
    if button.get_attribute("aria-pressed") != str(enabled).lower():
        button.click()
    expect(button).to_have_attribute("aria-pressed", str(enabled).lower())


def review_large_dashboard(page, prefix):
    reading_mode(page, True)
    for label, width in (("mobile-large", 390), ("narrow-large", 320)):
        capture(page, f"{prefix}-{label}", width, 844, "#dashboard")
        # The dashboard and its priority action need to fit independently of
        # the page; a clipped inner panel can otherwise hide overflowing text.
        for selector in ("#dashboard-main", ".overview-priority", ".overview-action-center"):
            metrics = page.locator(selector).evaluate(
                "el => ({content: el.scrollWidth, available: el.clientWidth})"
            )
            assert metrics["content"] <= metrics["available"] + 3, (prefix, width, selector, metrics)
    reading_mode(page, False)


def review_public_job_pages(page):
    """Inspect the same factual offer in its card, modal and shareable pages."""
    card = page.locator("#public-jobs .job-card").filter(has_text="Кладовщик")
    vacancy_id = int(card.get_attribute("data-job-id"))
    public_job = page.request.get(URL + f"/api/jobs/{vacancy_id}")
    assert public_job.status == 200, public_job.text()
    employer_id = int(public_job.json()["job"]["employer_id"])
    variants = (("desktop", 1366, 900, False),
                ("mobile-large", 390, 844, True), ("narrow-large", 320, 844, True))
    for label, width, height, large in variants:
        page.set_viewport_size({"width": width, "height": height})
        reading_mode(page, large)
        expect(card.locator(".job-essential-facts dt")).to_have_text(["Город", "График", "Занятость"])
        expect(card.locator("[data-v02-action='apply']")).to_have_count(0)
        expect(card.locator(".job-actions .btn-primary")).to_have_count(1)
        capture(page, f"01-vacancy-card-{label}", width, height,
                f'#public-jobs [data-job-id="{vacancy_id}"]')
        card.locator("[data-v02-action='details']").click()
        expect(page.locator("#job-dialog")).to_be_visible()
        expect(page.locator("#job-dialog .job-detail-action")).to_be_visible()
        capture(page, f"01-vacancy-detail-{label}", width, height, "#job-dialog")
        assert page.locator("#job-dialog").evaluate(
            "el => el.scrollWidth <= el.clientWidth + 3"
        ), "Vacancy modal should not scroll horizontally"
        capture(page, f"01-vacancy-action-{label}", width, height,
                "#job-dialog .job-detail-action")
        page.locator("#job-dialog-close").click()

    # Both public company URLs are used by existing navigation and must remain
    # readable. Contacts and profile controls remain outside these public views.
    pages = (
        ("vacancy-share", f"/vacancies/{vacancy_id}", ".vacancy-sheet"),
        ("company-share", f"/companies/{employer_id}", "#company-jobs"),
        ("employer-directory", "/employers", "#employer-cards"),
        ("employer-profile", f"/employers/{employer_id}", "#company-jobs"),
    )
    for name, path, content in pages:
        page.goto(URL + path, wait_until="networkidle")
        expect(page.locator(content)).to_be_visible()
        text = page.locator("body").inner_text()
        assert "company@demo.example" not in text and "Мария Тестовая" not in text
        for label, width, height, large in variants:
            page.set_viewport_size({"width": width, "height": height})
            reading_mode(page, large)
            capture(page, f"01-{name}-{label}", width, height)
    # Later private-dashboard screenshots preserve their existing normal mode.
    reading_mode(page, False)


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

                    review_public_job_pages(page)

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
                    review_large_dashboard(page, "02-candidate")

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
                        if label == "mobile":
                            assert page.evaluate("""() => {
                                const stats = document.querySelector('.employer-overview-stats');
                                const trust = document.querySelector('.employer-trust-overview');
                                return stats && trust &&
                                    stats.getBoundingClientRect().top < trust.getBoundingClientRect().top;
                            }"""), "Employer KPIs should appear above trust details on phones"
                    review_large_dashboard(page, "04-employer")
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
