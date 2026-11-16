"""Mobile end-to-end consent and contact-privacy rehearsal (fictional accounts only).

Runs against a freshly seeded LOCAL database. Never points at Timeweb or
production. All contact checks use fabricated demonstration values.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8771"
HEADERS = {"X-Requested-With": "OPYT50"}
CANDIDATE_EMAIL = "kladovshik@demo.example"
CANDIDATE_PHONE = "+70000000001"
LONG_DESCRIPTION = (
    "Работа кладовщиком в Подольске. График сменный, "
    "складской учёт и инвентаризация. "
    + "Оборудование и обучение на месте. " * 16
)


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


def no_contacts_exposed(response):
    assert response.status == 200, response.text()
    body = response.text()
    assert CANDIDATE_EMAIL not in body, "Employer saw email before unlock"
    assert CANDIDATE_PHONE not in body, "Employer saw phone before unlock"


def check_mobile_width(page, label):
    metrics = page.evaluate("""() => ({
      viewport: document.documentElement.clientWidth,
      width: document.documentElement.scrollWidth,
      dashboard: document.querySelector('#dashboard-main')?.scrollWidth,
      dashboardWidth: document.querySelector('#dashboard-main')?.clientWidth
    })""")
    assert metrics["width"] <= metrics["viewport"] + 3, (label, metrics)
    if metrics["dashboard"] is not None:
        assert metrics["dashboard"] <= metrics["dashboardWidth"] + 3, (label, metrics)


def exercise_mobile_introduction(page):
    # Create a real invitation through the employer API. It must not reveal
    # fictional candidate contact details before the later separate consent.
    login(page, "company@demo.example")
    jobs_response = page.request.get(URL + "/api/employer/vacancies")
    assert jobs_response.status == 200
    vacancy_id = next(
        job["id"] for job in jobs_response.json()["jobs"]
        if job["title"] == "Кладовщик"
    )
    match_response = page.request.get(
        URL + f"/api/employer/vacancies/{vacancy_id}/matches"
    )
    assert match_response.status == 200
    candidate_id = next(
        item["candidate_id"] for item in match_response.json()["matches"]
        if item["profession"] == "Кладовщик"
    )
    created = page.request.post(
        URL + "/api/employer/invitations", headers=HEADERS,
        data={"vacancy_id": vacancy_id, "candidate_id": candidate_id},
    )
    assert created.status == 201, created.text()
    invitation_id = created.json()["id"]
    no_contacts_exposed(page.request.get(URL + "/api/employer/invitations"))
    logout(page)

    login(page, CANDIDATE_EMAIL)
    expect(page.locator(".overview-priority h3")).to_have_text(
        "Ответьте на приглашение работодателя"
    )
    page.locator(
        ".overview-priority [data-action='open-candidate-invitations']"
    ).click()
    card = page.locator("#dashboard-main .candidate-introduction-card.is-decision")
    expect(card).to_have_count(1)
    expect(card.locator(".candidate-invitation-summary")).to_contain_text(
        "Работа кладовщиком в Подольске"
    )
    expect(card.locator(".candidate-invitation-conditions")).to_be_visible()
    expect(card.locator(".candidate-invitation-history")).not_to_have_attribute(
        "open", ""
    )
    assert page.evaluate("""() => {
      const card = document.querySelector('.candidate-introduction-card');
      const terms = card?.querySelector('.candidate-invitation-summary');
      const consent = card?.querySelector('.consent-box');
      const actions = card?.querySelector('.invitation-actions');
      const history = card?.querySelector('.candidate-invitation-history');
      return terms && consent && actions && history &&
        terms.getBoundingClientRect().top < consent.getBoundingClientRect().top &&
        consent.getBoundingClientRect().top < actions.getBoundingClientRect().top &&
        actions.getBoundingClientRect().top < history.getBoundingClientRect().top;
    }"""), "Mobile candidate must see terms and choice before the timeline"
    card.locator(".candidate-invitation-conditions summary").click()
    expect(card.locator(".candidate-invitation-conditions")).to_have_attribute(
        "open", ""
    )
    expect(card.locator(".candidate-invitation-conditions p")).to_contain_text(
        "Оборудование и обучение"
    )
    card.locator(".candidate-invitation-conditions summary").click()
    card.locator(".candidate-invitation-history summary").click()
    expect(card.locator(".candidate-invitation-history")).to_have_attribute(
        "open", ""
    )
    card.locator(".candidate-invitation-history summary").click()

    attempted = []
    page.on("request", lambda request: attempted.append(request.url) if (
        f"/api/candidate/invitations/{invitation_id}/respond" in request.url
        and request.method == "POST"
    ) else None)
    card.locator("[data-action='accept']").click()
    expect(page.locator("#toast")).to_contain_text(
        "Подтвердите согласие на передачу контакта"
    )
    assert not attempted, "Unchecked consent must not POST"
    card.locator(f"#consent-{invitation_id}").check()
    with page.expect_response(lambda response: (
        response.url.endswith(f"/api/candidate/invitations/{invitation_id}/respond")
        and response.request.method == "POST"
    )) as decision:
        card.locator("[data-action='accept']").click()
    assert decision.value.status == 200, decision.value.text()
    assert len(attempted) == 1
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие отправлено")
    expect(page.locator("#dashboard-main [data-action='accept']")).to_have_count(0)
    check_mobile_width(page, "candidate consent")
    logout(page)

    # Even after consent the employer must not get contacts automatically:
    # unlocking is a distinct action.
    login(page, "company@demo.example")
    no_contacts_exposed(page.request.get(URL + "/api/employer/invitations"))
    selector = page.locator("[data-dashboard-tab-select]")
    expect(selector).to_be_visible()
    selector.select_option("invitations")
    employer_card = page.locator(
        "#dashboard-main .employer-invitation-card.is-action"
    )
    expect(employer_card).to_have_count(1)
    expect(employer_card.locator("[data-action='demo-pay']")).to_be_visible()
    assert CANDIDATE_EMAIL not in page.locator("#dashboard-main").inner_text()
    page.once("dialog", lambda dialog: dialog.accept())
    employer_card.locator("[data-action='demo-pay']").click()
    expect(page.locator("#dashboard-main")).to_contain_text(
        "КОНТАКТ ОТКРЫТ · ДЕМО"
    )
    expect(page.locator("#dashboard-main")).to_contain_text(CANDIDATE_EMAIL)
    check_mobile_width(page, "employer contact")
    logout(page)

    login(page, CANDIDATE_EMAIL)
    page.locator("[data-dashboard-tab-select]").select_option("invitations")
    expect(page.locator("#dashboard-main")).to_contain_text(
        "Знакомство состоялось"
    )
    expect(page.locator("#dashboard-main [data-action='accept']")).to_have_count(0)
    check_mobile_width(page, "candidate introduced")
    page.locator("#reading-mode-toggle").click()
    expect(page.locator("#reading-mode-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    check_mobile_width(page, "candidate introduced large text")
    page.locator("#reading-mode-toggle").click()

    # The smallest supported phone keeps the consent history and controls
    # within the viewport (not a horizontally scrolling document).
    page.set_viewport_size({"width": 320, "height": 740})
    check_mobile_width(page, "320px")
    assert page.evaluate("""() => {
      const filter = document.querySelector('.candidate-introduction-stage-filter');
      return filter && getComputedStyle(filter).gridTemplateColumns.trim()
        .split(/\\s+/).length === 1;
    }"""), "320px stage filters should use one column"


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-introduction-") as temp:
        db_file = Path(temp) / "demo.db"
        env = dict(
            os.environ, OPYT50_DB_PATH=str(db_file),
            OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", str(db_file)],
            cwd=ROOT, env=env, capture_output=True, check=True,
        )
        # A longer fictional vacancy description exercises the expandable
        # conditions; nothing is ever written to an external environment.
        with sqlite3.connect(db_file) as db:
            db.execute(
                "UPDATE vacancies SET description=? WHERE title='Кладовщик'",
                (LONG_DESCRIPTION,),
            )
            db.commit()
        log_file = (Path(temp) / "server.log").open("w", encoding="utf-8")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8771"],
            cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT,
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
                raise RuntimeError("Mobile introduction test server unavailable")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, args=["--no-sandbox"]
                )
                try:
                    context = browser.new_context(
                        viewport={"width": 390, "height": 844},
                        locale="ru-RU",
                    )
                    try:
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        exercise_mobile_introduction(page)
                        assert not errors, errors
                        print("Mobile introduction, consent and contact privacy: PASSED")
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
            log_file.close()


if __name__ == "__main__":
    main()
