"""Employer comparison browser regression with isolated fictional profiles."""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8778"
HEADERS = {"X-Requested-With": "OPYT50"}
CANDIDATES = (81001, 81002, 81003, 81004)


def save_review(page, filename):
    review_dir = os.environ.get("STAZHNO_COMPARISON_REVIEW_DIR")
    if review_dir:
        destination = Path(review_dir)
        destination.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination / filename), full_page=False)


def run_comparison(page):
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    login = page.request.post(
        URL + "/api/login", headers=HEADERS,
        data={"email": "company@demo.example", "password": "DemoPass2026!"},
    )
    assert login.status == 200, login.text()
    jobs_response = page.request.get(URL + "/api/employer/vacancies")
    assert jobs_response.status == 200, jobs_response.text()
    jobs = jobs_response.json()["jobs"]
    job = next(item for item in jobs if item["title"] == "Кладовщик")
    other_job = next(item for item in jobs if item["id"] != job["id"] and item["status"] == "open")
    job_id = job["id"]
    original_matches = page.request.get(URL + f"/api/employer/vacancies/{job_id}/matches")
    assert original_matches.status == 200, original_matches.text()
    sample = original_matches.json()["matches"][0]
    original_invitations = page.request.get(URL + "/api/employer/invitations").json()

    # Use the actual public DTO shape, but never send fictional ids to the DB.
    # Extra private fields deliberately test the comparison's allowlist.
    fixtures = []
    for index, candidate_id in enumerate(CANDIDATES):
        item = copy.deepcopy(sample)
        item.update(
            candidate_id=candidate_id, profession=f"Кладовщик, профиль {index + 1}",
            salary_min=65000 + index * 5000, schedule="Сменный", employment="Полная",
            invitation_id=None, invitation_status=None, contact_shared=False,
            experience_years=18, education="Среднее профессиональное",
            achievements="Снизил число ошибок при учёте", specializations="Складской учёт",
            work_history=[{"position": "Старший кладовщик", "period": "2018–2025", "duties": "Учёт и приёмка"}],
            courses=[], name="PRIVATE_NAME_81000", email="private-81000@example.invalid",
            phone="+7 999 123-45-67", about="PRIVATE_ABOUT_81000",
            contact={"name": "PRIVATE_CONTACT_81000", "email": "contact-81000@example.invalid"},
            skills="1С, Excel, приёмка, отгрузка, инвентаризация, управление возвратами",
            cautions=[],
        )
        fixtures.append(item)
    fixtures[0]["profession"] = 'Кладовщик <b data-comparison-injection="yes">учёт</b>'
    fixtures[0]["skills"] += ', <img data-comparison-injection="yes" src="invalid">'
    fixtures[0]["cautions"] = [
        "Ваш минимум ближе к верхней границе зарплаты — уточните итоговое предложение"
    ]
    fixtures[1].update(
        salary_min=0, experience_years=0, education="", achievements="",
        specializations="", work_history=[], courses=[],
        cautions=["Не указаны в вашем профиле: Excel"],
    )
    for factor in fixtures[1]["score_breakdown"]:
        if factor["key"] == "salary":
            factor["text"] = "Минимальная зарплата в профиле не задана"
            factor["caution"] = ""
    fixtures[2].update(invitation_id=71003, invitation_status="accepted")

    def invitation(invitation_id, candidate_id, status):
        return {
            "id": invitation_id, "candidate_id": candidate_id,
            "candidate_profession": f"Кладовщик — знакомство {invitation_id}",
            "vacancy_id": job_id, "vacancy_title": job["title"],
            "status": status, "contact_shared": False, "contact": None,
            "created_at": "2026-11-20T09:00:00", "price_rub": 1000,
            "application_id": None, "application_status": None,
            "direct_outcome": None, "timeline": [],
        }

    invitation_fixtures = [
        invitation(71999, CANDIDATES[3], "accepted"),
        invitation(71003, CANDIDATES[2], "accepted"),
    ]
    invite_posts = []

    def fake_matches(route):
        assert route.request.method == "GET"
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"matches": fixtures}, ensure_ascii=False))

    def fake_invitations(route):
        request = route.request
        if request.method == "POST":
            payload = request.post_data_json
            invite_posts.append(payload)
            assert payload == {"vacancy_id": job_id, "candidate_id": CANDIDATES[1]}, payload
            invitation_fixtures.append(invitation(71002, CANDIDATES[1], "sent"))
            fixtures[1].update(invitation_id=71002, invitation_status="sent")
            route.fulfill(status=201, content_type="application/json",
                          body='{"id":71002,"created":true}')
        else:
            assert request.method == "GET"
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"invitations": invitation_fixtures}, ensure_ascii=False))

    page.route("**/api/employer/vacancies/*/matches", fake_matches)
    page.route("**/api/employer/invitations", fake_invitations)
    page.goto(URL, wait_until="networkidle")
    expect(page.locator("#dashboard")).to_be_visible()
    writes = []
    page.on("request", lambda request: writes.append((request.method, request.url))
            if "/api/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"}
            else None)
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()

    panel = page.locator("#employer-matches")
    comparison = page.locator("#employer-candidate-comparison")
    match_list = panel.locator("[data-employer-match-list]")
    show = panel.locator("[data-action='compare-show']")

    def open_matches(vacancy_id):
        page.locator(
            f".employer-vacancy-card[data-employer-vacancy-id='{vacancy_id}'] [data-action='matches']"
        ).click()
        expect(panel.locator(".candidate-match-card")).to_have_count(4)

    def toggle(candidate_id):
        return panel.locator(f"[data-action='compare-toggle-candidate'][data-id='{candidate_id}']")

    def cell(field, candidate_id):
        return comparison.locator(
            f".candidate-compare-row[data-compare-field='{field}'] [data-compare-candidate-id='{candidate_id}']"
        )

    def expect_empty_selection():
        expect(show).to_be_disabled()
        expect(panel.locator("[data-action='compare-toggle-candidate'][aria-pressed='true']")).to_have_count(0)
        for candidate_id in CANDIDATES:
            expect(toggle(candidate_id)).to_be_enabled()

    def show_comparison_heading():
        # Override the page's smooth-scroll CSS so capture never races with a
        # still-running animation from the homepage or the preceding action.
        comparison.evaluate("element => element.scrollIntoView({block:'start',behavior:'instant'})")
        assert page.evaluate("""() => {
          const heading = document.querySelector('#employer-candidate-comparison .candidate-comparison-heading h4');
          const header = document.querySelector('.site-header');
          const rect = heading.getBoundingClientRect();
          return rect.top >= (header?.getBoundingClientRect().bottom || 0) &&
            rect.bottom <= window.innerHeight;
        }"""), "Comparison heading must be visible below the sticky navigation"

    open_matches(job_id)
    expect(panel.locator("#employer-compare-status")).to_be_visible()
    expect_empty_selection()
    toggle(CANDIDATES[0]).click()
    expect(show).to_be_disabled()
    toggle(CANDIDATES[1]).click()
    expect(show).to_be_enabled()
    show.click()
    expect(comparison).to_be_visible()
    expect(comparison).to_be_focused()
    expect(comparison).to_have_attribute("role", "region")
    expect(comparison).to_have_attribute("tabindex", "-1")
    expect(match_list).to_be_hidden()
    expect(comparison.locator("table.candidate-compare-table")).to_have_count(1)
    for field in ("profession", "skills", "salary", "location", "schedule", "employment", "experience", "questions", "next"):
        expect(cell(field, CANDIDATES[0])).to_be_visible()
        expect(cell(field, CANDIDATES[1])).to_be_visible()
    for candidate_id in CANDIDATES[:2]:
        expect(comparison).to_contain_text(f"Анкета №{candidate_id}")
    expect(cell("skills", CANDIDATES[0])).to_contain_text("управление возвратами")
    expect(cell("skills", CANDIDATES[0])).to_contain_text('<img data-comparison-injection="yes" src="invalid">')
    expect(cell("profession", CANDIDATES[0])).to_contain_text('<b data-comparison-injection="yes">учёт</b>')
    expect(comparison.locator("[data-comparison-injection]")).to_have_count(0)
    expect(cell("salary", CANDIDATES[0])).to_contain_text(re.compile(r"65\s*000"))
    expect(cell("salary", CANDIDATES[1])).to_contain_text("Зарплата не указана")
    expect(cell("experience", CANDIDATES[0])).to_contain_text("18")
    expect(cell("experience", CANDIDATES[1])).to_contain_text("Не указано в резюме")
    expect(cell("questions", CANDIDATES[0])).to_contain_text("Минимум кандидата")
    expect(cell("questions", CANDIDATES[1])).to_contain_text("в профиле кандидата")
    expect(cell("questions", CANDIDATES[1])).to_contain_text("Excel")
    comparison_html = comparison.inner_html()
    for private_marker in ("PRIVATE_NAME_81000", "PRIVATE_ABOUT_81000", "PRIVATE_CONTACT_81000",
                           "private-81000@example.invalid", "contact-81000@example.invalid", "+7 999 123-45-67"):
        assert private_marker not in comparison_html, f"Comparison leaked {private_marker}"
    assert "Ваш минимум" not in comparison.inner_text()
    assert "вашем профиле" not in comparison.inner_text()

    # The neutral summary identifies factual differences and clarification counts,
    # without ranking candidates or showing contact information.
    summary = comparison.locator('[aria-label="Краткое резюме сравнения"]')
    expect(summary).to_be_visible()
    expect(summary).to_contain_text("Различаются:")
    expect(summary).to_contain_text("профессия и специализация")
    expect(summary).to_contain_text("зарплатные ожидания")
    expect(summary).to_contain_text(f"Анкета №{CANDIDATES[0]}: вопросов для уточнения")
    assert "PRIVATE_NAME_81000" not in summary.inner_text()

    # The focus switch hides only identical professional criteria. Scores,
    # clarification questions and safe next steps must remain visible.
    differences = comparison.locator('[data-action="compare-differences"]')
    expect(differences).to_have_attribute("aria-pressed", "false")
    differences.click()
    expect(differences).to_have_attribute("aria-pressed", "true")
    expect(comparison.locator('[data-compare-field="schedule"]')).to_be_hidden()
    expect(comparison.locator('[data-compare-field="employment"]')).to_be_hidden()
    for field in ("score", "profession", "salary", "experience", "questions", "next"):
        expect(comparison.locator(f'[data-compare-field="{field}"]')).to_be_visible()
    expect(cell("next", CANDIDATES[1]).locator('[data-action="invite"]')).to_be_visible()
    assert not writes, "Filtering the comparison must not write to the API"
    differences.click()
    expect(differences).to_have_attribute("aria-pressed", "false")
    expect(comparison.locator('[data-compare-field="schedule"]')).to_be_visible()

    # Returning retains the selected pair; the fourth profile cannot silently
    # replace someone when the three-person limit is reached.
    panel.locator("[data-action='compare-back']").click()
    expect(match_list).to_be_visible()
    for candidate_id in CANDIDATES[:2]:
        expect(toggle(candidate_id)).to_have_attribute("aria-pressed", "true")
    show.click()
    cell("next", CANDIDATES[0]).locator("[data-action='compare-open-profile']").click()
    resume_card = panel.locator(f".candidate-match-card[data-match-candidate-id='{CANDIDATES[0]}']")
    expect(resume_card).to_be_focused()
    expect(resume_card.locator(".candidate-resume-details")).to_have_attribute("open", "")
    for candidate_id in CANDIDATES[:2]:
        expect(toggle(candidate_id)).to_have_attribute("aria-pressed", "true")
    toggle(CANDIDATES[2]).click()
    expect(toggle(CANDIDATES[3])).to_be_disabled()
    toggle(CANDIDATES[3]).evaluate("button => button.click()")
    expect(toggle(CANDIDATES[3])).to_have_attribute("aria-pressed", "false")
    expect(panel.locator("[data-action='compare-toggle-candidate'][aria-pressed='true']")).to_have_count(3)
    toggle(CANDIDATES[1]).click()
    expect(toggle(CANDIDATES[3])).to_be_enabled()
    toggle(CANDIDATES[3]).click()
    expect(toggle(CANDIDATES[1])).to_be_disabled()
    toggle(CANDIDATES[3]).click()
    toggle(CANDIDATES[1]).click()
    show.click()
    expect(cell("profession", CANDIDATES[2])).to_be_visible()
    show_comparison_heading()
    save_review(page, "comparison-desktop.png")

    page.set_viewport_size({"width": 390, "height": 844})
    for comfortable in (False, True):
        if comfortable:
            page.locator("#reading-mode-toggle").click()
            expect(page.locator("#reading-mode-toggle")).to_have_attribute("aria-pressed", "true")
        assert page.evaluate("""() => {
          const root = document.querySelector('#dashboard-main');
          const comparison = document.querySelector('#employer-candidate-comparison');
          const buttons = [...document.querySelectorAll(
            '#employer-matches .candidate-compare-toolbar button, #employer-candidate-comparison button'
          )].filter(button =>
            !button.hidden && button.getClientRects().length > 0
          );
          return root.scrollWidth <= root.clientWidth + 3 &&
            comparison.scrollWidth <= comparison.clientWidth + 3 &&
            buttons.length > 0 && buttons.every(button => button.getBoundingClientRect().height >= 44);
        }"""), f"Comparison must fit 390px with touch-sized controls (comfortable={comfortable})"
        show_comparison_heading()
        save_review(page, "comparison-mobile-comfortable.png" if comfortable else "comparison-mobile.png")
        next_row = comparison.locator("[data-compare-field='next']")
        next_row.evaluate("""element => {
          const headerHeight = document.querySelector('.site-header')?.getBoundingClientRect().height || 0;
          window.scrollTo({top:window.scrollY + element.getBoundingClientRect().top - headerHeight - 16,
            behavior:'instant'});
        }""")
        assert next_row.evaluate("""element => {
          const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0;
          const heading = element.querySelector('th').getBoundingClientRect();
          const button = element.querySelector('button').getBoundingClientRect();
          return heading.top >= headerBottom && heading.bottom <= window.innerHeight &&
            button.top >= headerBottom && button.bottom <= window.innerHeight;
        }"""), "Mobile review image must show the next-step heading and an action control"
        save_review(page, "comparison-mobile-comfortable-actions.png" if comfortable else "comparison-mobile-actions.png")
    page.locator("#reading-mode-toggle").click()
    page.set_viewport_size({"width": 1280, "height": 820})

    # Clear is available directly from the comparison, without losing vacancy
    # context. Switching vacancies and closing the panel also reset selection.
    panel.locator("[data-action='compare-clear']:visible").click()
    expect(match_list).to_be_visible()
    expect_empty_selection()
    toggle(CANDIDATES[0]).click()
    toggle(CANDIDATES[1]).click()
    show.click()
    open_matches(other_job["id"])
    expect_empty_selection()
    open_matches(job_id)
    expect_empty_selection()
    toggle(CANDIDATES[0]).click()
    toggle(CANDIDATES[1]).click()
    panel.locator("[data-action='close-employer-matches']").click()
    expect(panel).to_be_hidden()
    open_matches(job_id)
    expect_empty_selection()
    assert not writes, "Selection, comparison and vacancy navigation must make no API writes: " + str(writes)

    # Existing consent routes to the exact introduction, even when another
    # consented invitation would otherwise be first. It never opens contacts.
    toggle(CANDIDATES[0]).click()
    toggle(CANDIDATES[2]).click()
    show.click()
    existing = cell("next", CANDIDATES[2]).locator("[data-action='open-employer-invitations']")
    expect(existing).to_have_attribute("data-invitation-id", "71003")
    expect(existing).to_have_attribute("data-vacancy-id", str(job_id))
    existing.click()
    destination = page.locator(".employer-invitation-card[data-invitation-id='71003']")
    expect(destination).to_be_visible()
    expect(destination).to_be_focused()
    expect(page.locator("[data-employer-introduction-vacancy-filter]")).to_have_value(str(job_id))
    expect(destination.locator("[data-action='demo-pay']")).to_be_visible()
    assert not writes, "Opening an existing introduction must not request contact access"

    # There are two buttons for the same pair while the list is hidden.
    # Repeated dispatch across both must produce exactly one invitation POST.
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()
    open_matches(job_id)
    toggle(CANDIDATES[0]).click()
    toggle(CANDIDATES[1]).click()
    show.click()
    invite_button = cell("next", CANDIDATES[1]).locator("[data-action='invite']")
    expect(invite_button).to_have_attribute("data-job", str(job_id))
    expect(invite_button).to_have_attribute("data-id", str(CANDIDATES[1]))
    assert page.evaluate("""({candidateId, jobId}) => {
      const pair = '[data-action="invite"][data-id="' + candidateId + '"][data-job="' + jobId + '"]';
      if (document.querySelectorAll('#employer-matches ' + pair).length !== 2) return false;
      document.querySelector('#employer-candidate-comparison ' + pair).click();
      // A fresh copy is deliberately re-enabled to simulate a stale/rebuilt
      // control. The pair-level guard must hold beyond button disabling.
      const duplicate = document.querySelector('[data-employer-match-list] ' + pair);
      if (!duplicate || !duplicate.disabled) return false;
      duplicate.disabled = false;
      duplicate.click();
      duplicate.click();
      return true;
    }""", {"candidateId": CANDIDATES[1], "jobId": job_id}), "Both comparison and list must route the same invitation pair"
    sent = page.locator(".employer-invitation-card[data-invitation-id='71002']")
    expect(sent).to_be_visible()
    expect(sent).to_be_focused()
    expect(sent).to_contain_text("Ждём решения кандидата")
    assert invite_posts == [{"vacancy_id": job_id, "candidate_id": CANDIDATES[1]}], invite_posts
    assert writes == [("POST", URL + "/api/employer/invitations")], writes
    # APIRequestContext bypasses page routes: the real local database must
    # remain unchanged by the fictional invitation or comparison operations.
    assert page.request.get(URL + "/api/employer/invitations").json() == original_invitations
    assert not browser_errors, "Uncaught browser errors: " + " | ".join(browser_errors)


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-candidate-comparison-") as tmp:
        env = dict(os.environ, OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
                   OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0")
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT, env=env, check=True, capture_output=True,
        )
        log_path = Path(tmp) / "uvicorn.log"
        with log_path.open("w", encoding="utf-8") as server_log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8778"],
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
                    raise RuntimeError("Local comparison server did not become ready")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                    try:
                        context = browser.new_context(viewport={"width": 1280, "height": 820}, locale="ru-RU")
                        page = context.new_page()
                        try:
                            run_comparison(page)
                        except Exception:
                            save_review(page, "comparison-failure.png")
                            server_log.flush()
                            print("Uvicorn error log:\n" + log_path.read_text(encoding="utf-8")[-10000:], file=sys.stderr)
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
                    server.wait(timeout=5)
    print("Browser candidate comparison: anonymous comparison, mobile, selection and safe invitations PASSED")


if __name__ == "__main__":
    main()
