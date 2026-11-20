"""Candidate resume editing, committed snapshots and privacy in a local browser."""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8784"
HEADERS = {"X-Requested-With": "OPYT50"}
BASE_ROLE = "Кладовщик участка"
BASE_COURSE = "Учёт складских запасов"
EDITED_ROLE = "Старший кладовщик участка"
EDITED_COURSE = "Управление запасами и инвентаризация"


def saved_user(page):
    response = page.request.get(URL + "/api/me")
    assert response.status == 200, response.text()
    return response.json()["user"]


def section(page, selector, opened=True):
    details = page.locator(selector)
    if details.evaluate("element => element.open") != opened:
        details.locator(":scope > summary").click()


def dirty(page):
    expect(page.locator("#profile-form .editor-save-status")).to_contain_text(
        "Есть несохранённые изменения"
    )


def refuse_navigation(page, field, value):
    dialogs = []
    page.once("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.locator("[data-dashboard-tab-select]").select_option("applications")
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("profile")
    expect(field).to_have_value(value)
    assert len(dialogs) == 1 and "несохранённые" in dialogs[0]
    assert page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable: true});
        window.dispatchEvent(event);
        return event.defaultPrevented;
    }"""), "Unsaved resume details must also protect a page reload"


def exercise_editor(page, review_dir):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    login = page.request.post(URL + "/api/login", headers=HEADERS, data={
        "email": "kladovshik@demo.example", "password": "DemoPass2026!",
    })
    assert login.status == 200, login.text()
    initial = saved_user(page)
    profile = initial["profile"] | {
        "phone": "+79999990001", "is_active": True,
        "work_history": [{"position": BASE_ROLE, "period": "2014–2024", "duties": "Приёмка поставок"}],
        "courses": [{"title": BASE_COURSE, "provider": "Учебный центр", "year": 2021, "has_certificate": True}],
    }
    seed = page.request.put(URL + "/api/candidate/profile", headers=HEADERS, data=profile)
    assert seed.status == 200, seed.text()
    baseline = saved_user(page)
    page.goto(URL, wait_until="networkidle")
    page.locator("[data-dashboard-tab-select]").select_option("profile")
    expect(page.locator("#profile-form")).to_have_attribute("data-editor-ready", "1")
    writes = []
    page.on("request", lambda request: writes.append(request) if (
        request.url.endswith("/api/candidate/profile") and request.method == "PUT"
    ) else None)

    # Editing a previously saved, unnamed work/course control must protect it
    # just like profession or city. Restoring the exact value clears the draft.
    section(page, "#resume-history-section")
    position = page.locator("[data-role-position]").first
    position.fill(EDITED_ROLE)
    dirty(page)
    refuse_navigation(page, position, EDITED_ROLE)
    position.fill(BASE_ROLE)
    expect(page.locator("#profile-form .editor-save-status")).not_to_contain_text("несохранённые")
    section(page, "#resume-training-section")
    course = page.locator("[data-course-title]").first
    course.fill(EDITED_COURSE)
    dirty(page)
    refuse_navigation(page, course, EDITED_COURSE)
    course.fill(BASE_COURSE)
    expect(page.locator("#profile-form .editor-save-status")).not_to_contain_text("несохранённые")

    # Row structure itself is part of the draft, including a newly added empty
    # entry. Removing that same row returns to the saved baseline.
    for add, rows, remove in (
        ("#resume-add-role", "[data-resume-role]", "[data-action='remove-resume-role']"),
        ("#resume-add-course", "[data-resume-course]", "[data-action='remove-resume-course']"),
    ):
        page.locator(add).click()
        expect(page.locator(rows)).to_have_count(2)
        dirty(page)
        page.locator(rows).last.locator(remove).click()
        expect(page.locator(rows)).to_have_count(1)
        expect(page.locator("#profile-form .editor-save-status")).not_to_contain_text("несохранённые")
    page.locator("[data-action='remove-resume-course']").click()
    dirty(page)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("[data-dashboard-tab-select]").select_option("overview")
    page.locator("[data-dashboard-tab-select]").select_option("profile")
    expect(page.locator("[data-resume-course]")).to_have_count(1)
    assert writes == [], "Draft navigation and row editing must not save the profile"

    section(page, "#resume-history-section")
    section(page, "#resume-training-section")
    section(page, "details.profile-optional")
    page.locator("[data-role-position]").first.fill(EDITED_ROLE)
    page.locator("[data-course-title]").first.fill(EDITED_COURSE)
    page.locator("#profile-about").fill(
        "Приёмка поставок. draft-contact@example.invalid, +7 999 000-11-22, https://example.invalid/contact"
    )
    page.locator("#profile-phone").fill("+79999990002")
    page.locator("#profile-salary").fill("")
    page.locator("#profile-active").uncheck()
    page.locator("[data-action='open-candidate-profile-preview']").first.click()
    preview = page.locator(".profile-public-preview")
    expect(preview).to_contain_text(EDITED_ROLE)
    expect(preview).to_contain_text(EDITED_COURSE)
    expect(preview).to_contain_text("Приёмка поставок")
    expect(page.locator("#candidate-profile-preview-state")).to_contain_text("несохранённые")
    text = preview.inner_text()
    for private in (
        baseline["name"], baseline["email"], "+79999990002",
        "draft-contact@example.invalid", "+7 999 000-11-22", "https://example.invalid/contact",
    ):
        assert private not in text, f"Preview disclosed private content: {private}"
    assert not re.search(r"\b0\s*₽", text)
    assert saved_user(page)["profile"] == baseline["profile"]
    assert writes == []

    # Printing is explicitly the last saved resume, even when the on-screen
    # preview already shows the current draft.
    page.locator("[data-action='open-resume-print']").click()
    expect(page.locator("#resume-print-document")).to_contain_text(BASE_ROLE)
    expect(page.locator("#resume-print-document")).not_to_contain_text(EDITED_ROLE)
    page.locator("[data-resume-print='close']").click()

    # A collapsed invalid section must open and focus the actionable field,
    # without submitting or leaving the whole editor stuck in saving state.
    for details, control, invalid, restored in (
        ("#resume-history-section", "[data-role-position]", "", EDITED_ROLE),
        ("#resume-training-section", "[data-course-title]", "", EDITED_COURSE),
        ("#resume-training-section", "[data-course-year]", "1949", "2024"),
    ):
        section(page, details)
        field = page.locator(control).first
        field.fill(invalid)
        section(page, details, False)
        page.locator("#profile-form button[type='submit']").click()
        expect(page.locator(details)).to_have_attribute("open", "")
        expect(field).to_be_focused()
        expect(page.locator("#profile-form button[type='submit']")).to_be_enabled()
        assert writes == [], "Invalid resume information reached the server"
        field.fill(restored)

    def offline(route):
        route.abort("failed")

    page.route("**/api/candidate/profile", offline)
    page.locator("#profile-form button[type='submit']").click()
    expect(page.locator("#profile-form .editor-save-status")).to_contain_text("Соединение прервалось")
    expect(page.locator("[data-role-position]").first).to_have_value(EDITED_ROLE)
    expect(page.locator("[data-course-title]").first).to_have_value(EDITED_COURSE)
    expect(page.locator("#profile-form button[type='submit']")).to_be_enabled()
    expect(page.locator("#profile-form")).not_to_have_attribute("inert", "")
    assert len(writes) == 1
    assert saved_user(page)["profile"] == baseline["profile"]
    page.unroute("**/api/candidate/profile", offline)

    pending = []
    me_calls = []

    def hold_save(route):
        pending.append(route)

    def unavailable_session(route):
        me_calls.append(route.request.url)
        route.fulfill(status=503, content_type="application/json", body='{"detail":"Временно недоступно"}')

    page.route("**/api/candidate/profile", hold_save)
    page.route("**/api/me", unavailable_session)
    with page.expect_request(lambda request: (
        request.url.endswith("/api/candidate/profile") and request.method == "PUT"
    )):
        page.evaluate("""() => {
            const button = document.querySelector('#profile-form button[type=submit]');
            button.click(); button.click();
        }""")
    deadline = time.monotonic() + 5
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    expect(page.locator("#profile-form")).to_have_attribute("inert", "")
    expect(page.locator("#profile-form button[type='submit']")).to_be_disabled()
    assert len(pending) == 1 and len(writes) == 2
    # A real pointer click, unlike JS .click(), respects inert. This covers the
    # search switch, which used to sit outside the saving form.
    toggle = page.locator("#profile-active")
    label = page.locator("label.switch-control")
    label.scroll_into_view_if_needed()
    box = label.bounding_box()
    assert box is not None
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(toggle).not_to_be_checked()
    page.locator("#profile-form").dispatch_event("submit")
    assert len(pending) == 1 and len(writes) == 2, "Pending save sent a duplicate PUT"
    reply = pending[0].fetch()
    assert reply.status == 200, reply.text()
    committed = reply.json()["profile"]
    pending[0].fulfill(response=reply)
    expect(page.locator("#profile-form .editor-save-status")).to_have_text("Изменения сохранены.")
    expect(page.locator("#profile-form")).not_to_have_attribute("inert", "")
    expect(page.locator("#candidate-profile-preview-state")).to_contain_text("сохранённая версия")
    expect(preview).to_contain_text(EDITED_ROLE)
    expect(page.locator(".profile-visibility")).to_contain_text("паузе")
    assert me_calls == [], "A committed save must not depend on a second /api/me request"
    assert committed["salary_min"] == 0 and not committed["is_active"]
    assert committed["work_history"][0]["position"] == EDITED_ROLE
    assert committed["courses"][0]["title"] == EDITED_COURSE
    page.unroute("**/api/candidate/profile", hold_save)
    page.unroute("**/api/me", unavailable_session)
    latest = saved_user(page)
    assert latest["profile"] == committed
    assert latest["phone"] == "+79999990002"

    page.locator("[data-action='open-resume-print']").click()
    printed = page.locator("#resume-print-document")
    expect(printed).to_contain_text(EDITED_ROLE)
    expect(printed).to_contain_text(EDITED_COURSE)
    assert not re.search(r"\b0\s*₽", printed.inner_text())
    expect(printed).not_to_contain_text("+79999990002")
    page.locator("#resume-print-include-contacts").check()
    expect(printed).to_contain_text("+79999990002")
    expect(printed).not_to_contain_text("draft-contact@example.invalid")
    page.locator("[data-resume-print='close']").click()
    dialogs = []
    page.once("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.locator("[data-dashboard-tab-select]").select_option("overview")
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("overview")
    assert dialogs == [], "Saved rows still trigger a discard-draft warning"
    page.locator("[data-dashboard-tab-select]").select_option("profile")

    # Keep the more demanding expanded editor and preview readable at the
    # narrow widths used by the audience, with the existing large-text option.
    section(page, "#resume-history-section")
    section(page, "#resume-training-section")
    page.locator("[data-action='open-candidate-profile-preview']").first.click()
    if page.locator("#reading-mode-toggle").get_attribute("aria-pressed") != "true":
        page.locator("#reading-mode-toggle").click()
    for width in (390, 320):
        page.set_viewport_size({"width": width, "height": 844})
        dimensions = page.evaluate("""() => ({
            viewport: document.documentElement.clientWidth,
            document: document.documentElement.scrollWidth,
            panels: [...document.querySelectorAll('#profile-form, .profile-public-preview')]
                .map(element => ({width: element.clientWidth, scroll: element.scrollWidth}))
        })""")
        assert dimensions["document"] <= dimensions["viewport"] + 2, dimensions
        assert all(panel["scroll"] <= panel["width"] + 2 for panel in dimensions["panels"]), dimensions
        page.locator(".candidate-profile").screenshot(path=str(review_dir / f"profile-{width}-large.png"))
    assert len(writes) == 2, "Preview, print or layout checks unexpectedly saved the profile"
    assert errors == [], errors


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-profile-editor-") as tmp:
        review_dir = Path(os.getenv("STAZHNO_PROFILE_REVIEW_DIR", str(Path(tmp) / "review")))
        review_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
                   OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0")
        subprocess.run([sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        log_path = Path(tmp) / "uvicorn.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen([
                sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8784",
            ], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(80):
                    try:
                        with urlopen(URL + "/api/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        time.sleep(.25)
                else:
                    raise RuntimeError("Local profile editor server did not become ready")
                with sync_playwright() as playwright:
                    options = {"headless": True, "args": ["--no-sandbox"]}
                    if os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
                        options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"]
                    browser = playwright.chromium.launch(**options)
                    try:
                        page = browser.new_page(viewport={"width": 390, "height": 844}, locale="ru-RU")
                        try:
                            exercise_editor(page, review_dir)
                        except Exception:
                            page.screenshot(path=str(review_dir / "failure.png"), full_page=True)
                            log.flush()
                            print(log_path.read_text(encoding="utf-8")[-10000:], file=sys.stderr)
                            raise
                    finally:
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
    print("Browser profile editor smoke: draft, save, preview, PDF and narrow layouts PASSED")


if __name__ == "__main__":
    main()
