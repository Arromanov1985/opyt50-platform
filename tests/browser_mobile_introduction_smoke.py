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


def introduction_destination(page, role, invitation_id, stage, focused=False):
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("invitations")
    expect(page.locator(f"[data-{role}-introduction-search]")).to_have_value("")
    expect(page.locator(f"[data-action='filter-{role}-invitations'][data-filter='{stage}']")).to_have_attribute(
        "aria-pressed", "true"
    )
    card_class = "candidate-introduction-card" if role == "candidate" else "employer-invitation-card"
    card = page.locator(f"#dashboard-main .{card_class}[data-invitation-id='{invitation_id}']")
    expect(card).to_be_visible()
    if focused:
        expect(card).to_be_focused()
    return card


def exercise_mobile_introduction(page):
    writes = []
    page.on("request", lambda request: writes.append((request.method, request.url))
            if "/api/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"}
            else None)
    # Create a real invitation through the employer's matching action. It must not reveal
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
    selector = page.locator("[data-dashboard-tab-select]")
    selector.select_option("invitations")
    page.locator("[data-employer-introduction-search]").fill("прошлый поиск")
    page.locator("[data-action='filter-employer-invitations'][data-filter='closed']").click()
    selector.select_option("vacancies")
    page.locator(f"[data-action='matches-primary'][data-id='{vacancy_id}']").click()
    with page.expect_response(lambda response: (
        response.url.endswith("/api/employer/invitations") and response.request.method == "POST"
    )) as created:
        page.locator(f"[data-action='invite'][data-job='{vacancy_id}'][data-id='{candidate_id}']").click()
    assert created.value.status == 201, created.value.text()
    invitation_id = created.value.json()["id"]
    introduction_destination(page, "employer", invitation_id, "waiting", focused=True)
    expect(page.locator("[data-employer-introduction-vacancy-filter]")).to_have_value(str(vacancy_id))
    assert len([entry for entry in writes if entry == ("POST", URL + "/api/employer/invitations")]) == 1
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
    card.locator(".candidate-invitation-history > summary").click()
    expect(card.locator(".candidate-invitation-history")).to_have_attribute(
        "open", ""
    )
    card.locator(".candidate-invitation-history > summary").click()

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
    page.locator("[data-employer-introduction-search]").fill("нет такого кандидата")
    expect(page.locator(".employer-invitation-card:visible")).to_have_count(0)
    selector.select_option("overview")
    expect(page.locator(".overview-stat-card[data-filter='action'] strong")).to_have_text("1")
    before_navigation = len(writes)
    page.locator(".overview-priority [data-action='open-employer-invitations'][data-filter='action']").click()
    employer_card = introduction_destination(page, "employer", invitation_id, "action")
    assert len(writes) == before_navigation, "Opening a consented introduction must not unlock contacts"
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
    expect(page.locator(".overview-priority h3")).to_have_text("Контакты уже переданы работодателю")
    expect(page.locator(".overview-stat-card[data-action='open-candidate-invitations'] strong")).to_have_text("1")
    selector.select_option("invitations")
    page.locator("[data-candidate-introduction-search]").fill("нет такой компании")
    expect(page.locator(".candidate-introduction-card:visible")).to_have_count(0)
    selector.select_option("overview")
    before_navigation = len(writes)
    page.locator(".overview-priority [data-action='open-candidate-invitations'][data-filter='introduced']").click()
    introduction_destination(page, "candidate", invitation_id, "introduced")
    assert len(writes) == before_navigation, "Opening the status must not repeat candidate consent"
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

    # Release 0.5.25: direct introductions now have a final result even when
    # the candidate never submitted an application. This stays a separate
    # invitation workflow, without creating a fictitious application.
    logout(page)
    login(page, "company@demo.example")
    expect(page.locator(".overview-stat-card[data-filter='introduced'] strong")).to_have_text("1")
    expect(page.locator(".overview-priority [data-action='open-employer-invitations'][data-filter='introduced']")).to_be_visible()
    selector.select_option("invitations")
    page.locator("[data-employer-introduction-search]").fill("нет такого кандидата")
    expect(page.locator(".employer-invitation-card:visible")).to_have_count(0)
    selector.select_option("overview")
    before_navigation = len(writes)
    page.locator(".overview-priority [data-action='open-employer-invitations'][data-filter='introduced']").click()
    introduction_destination(page, "employer", invitation_id, "introduced")
    assert len(writes) == before_navigation, "Opening the outcome queue must not record an outcome"

    # A direct introduction has no application row, but still gives the
    # employer a next action in the vacancy worklist and its attention filter.
    selector.select_option("vacancies")
    attention = page.locator("[data-action='filter-employer-jobs'][data-filter='attention']")
    expect(attention).to_contain_text("Требуют внимания (1)")
    attention.click()
    vacancy_card = page.locator(f".employer-vacancy-card[data-employer-vacancy-id='{vacancy_id}']")
    expect(page.locator(".employer-vacancy-card:visible")).to_have_count(1)
    expect(vacancy_card).to_be_visible()
    expect(vacancy_card.locator(".vacancy-pipeline-mini > span").filter(has_text="Ждут итога").locator("strong")).to_have_text("1")
    before_navigation = len(writes)
    vacancy_card.locator(".employer-vacancy-primary [data-action='open-employer-invitations'][data-filter='introduced']").click()
    direct_card = introduction_destination(page, "employer", invitation_id, "introduced")
    expect(page.locator("[data-employer-introduction-vacancy-filter]")).to_have_value(str(vacancy_id))
    assert len(writes) == before_navigation, "Vacancy next action must only open the existing introduction"
    completed_before = page.request.get(URL + "/api/employer/invitations")
    assert completed_before.status == 200
    direct_case = next(item for item in completed_before.json()["invitations"]
                       if item["id"] == invitation_id)
    assert direct_case["application_id"] is None
    assert direct_case["direct_outcome"] is None
    expect(direct_card.locator("[data-action='direct-introduction-outcome']")).to_have_count(2)
    page.once("dialog", lambda dialog: dialog.accept())
    direct_card.locator("[data-action='direct-introduction-outcome'][data-status='hired']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог")
    expect(page.locator("#dashboard-main .employer-invitation-card.is-closed")).to_have_count(1)
    expect(page.locator("#dashboard-main [data-action='direct-introduction-outcome']")).to_have_count(0)
    check_mobile_width(page, "employer direct outcome")
    selector.select_option("overview")
    expect(page.locator(".overview-stat-card[data-filter='introduced'] strong")).to_have_text("0")
    selector.select_option("vacancies")
    expect(page.locator("[data-action='filter-employer-jobs'][data-filter='attention']")).to_contain_text(
        "Требуют внимания (0)"
    )
    logout(page)

    login(page, CANDIDATE_EMAIL)
    outcome_alert = page.locator(".candidate-outcome-alert.is-positive")
    expect(outcome_alert).to_contain_text("Положительный итог знакомства")
    expect(outcome_alert).not_to_contain_text("не договорились")
    selector.select_option("invitations")
    expect(page.locator(f".candidate-introduction-card[data-invitation-id='{invitation_id}']")).to_be_visible()
    page.locator("[data-candidate-introduction-search]").fill("нет такой компании")
    # Wait for the debounced search itself to hide the completed record before
    # changing stages; an already empty stage cannot prove the query applied.
    expect(page.locator(".candidate-introduction-card:visible")).to_have_count(0)
    page.locator("[data-action='filter-candidate-invitations'][data-filter='decision']").click()
    expect(page.locator(".candidate-introduction-card:visible")).to_have_count(0)
    selector.select_option("overview")
    before_navigation = len(writes)
    outcome_alert.locator(
        f"[data-action='open-candidate-invitations'][data-invitation-id='{invitation_id}']"
    ).click()
    introduction_destination(page, "candidate", invitation_id, "closed", focused=True)
    assert len(writes) == before_navigation, "Viewing the result must not create or change an application"
    expect(page.locator("#dashboard-main .candidate-introduction-card.is-closed")).to_have_count(1)
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог знакомства")
    expect(page.locator("#dashboard-main")).to_contain_text("не подтверждение трудоустройства")
    assert page.request.get(URL + "/api/candidate/applications").json()["applications"] == []
    check_mobile_width(page, "candidate direct outcome")

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
            # account_controls is created by server startup migrations. The
            # overview test separately retains unverified-email precedence.
            with sqlite3.connect(db_file) as db:
                db.execute(
                    "INSERT INTO account_controls(user_id,email_verified) "
                    "SELECT id,1 FROM users WHERE email=? "
                    "ON CONFLICT(user_id) DO UPDATE SET email_verified=1",
                    (CANDIDATE_EMAIL,),
                )
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
