"""Aggregate route reporting and accessible navigation on fictional local data."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-Requested-With": "OPYT50"}
OUTPUT = Path(os.getenv(
    "STAZHNO_GROWTH_REVIEW_DIR", str(Path(tempfile.gettempdir()) / "stazhno-growth-review")
))
PATHS = (
    ("nayti-rabotu", "jobs_click", "/#jobs"),
    ("novye-navyki", "jobs_click", "/#jobs"),
    ("delitsya-opytom", "community_click", "/community"),
)


def checked(response, statuses=(200, 201)):
    assert response.status in statuses, f"{response.status}: {response.text()}"
    return response.json()


def no_overflow(page):
    dimensions = page.evaluate("""() => ({
        viewport: document.documentElement.clientWidth,
        document: document.documentElement.scrollWidth
    })""")
    if dimensions["document"] > dimensions["viewport"] + 2:
        dimensions["overflowing_elements"] = page.evaluate("""() => {
          const width = document.documentElement.clientWidth;
          const label = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
            + (el.classList.length ? '.' + [...el.classList].join('.') : '');
          const details = el => {
            const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
            return {element:label(el), left:rect.left, right:rect.right, width:rect.width,
              minWidth:style.minWidth, gridColumns:style.gridTemplateColumns,
              fontSize:style.fontSize, overflowX:style.overflowX};
          };
          return [...document.querySelectorAll('body *')].filter(el => {
            const rect = el.getBoundingClientRect();
            if (!rect.width || !rect.height || (rect.right <= width + 2 && rect.left >= -2)) return false;
            // Deliberate inner table scrolling must not obscure the actual
            // document-overflow culprit in the diagnostic output.
            for (let parent = el.parentElement; parent; parent = parent.parentElement) {
              const style = getComputedStyle(parent), box = parent.getBoundingClientRect();
              if (['auto','scroll','hidden','clip'].includes(style.overflowX)
                && box.left >= 0 && box.right <= width + 2) return false;
            }
            return true;
          }).slice(0,12).map(el => ({...details(el),
            parent:el.parentElement ? details(el.parentElement) : null}));
        }""")
        raise AssertionError(dimensions)


def capture(page, name):
    no_overflow(page)
    page.screenshot(path=str(OUTPUT / (name + ".png")), full_page=True)


def matches_event(request, source, action):
    return (request.url.endswith("/api/growth/event") and request.method == "POST"
            and request.post_data_json == {"source": source, "action": action})


def assert_destination(page, base, destination):
    if destination == "/community":
        # The directory normalizes its first page in history.replaceState.
        expect(page).to_have_url(re.compile("^" + re.escape(base + destination) + r"(?:\?page=1)?$"))
        expect(page.locator("#community-main")).to_be_visible()
    else:
        expect(page).to_have_url(base + destination)


def send(page, base, source, action):
    response = page.request.post(base + "/api/growth/event", headers=HEADERS,
                                 data={"source": source, "action": action})
    assert response.status == 204, response.text()


def serve_with_receipts(port, receipts_path):
    """Test-only wire evidence: store header presence, never cookie values."""
    sys.path.insert(0, str(ROOT))
    from app.main import app
    import uvicorn

    async def observed_app(scope, receive, send_response):
        if scope["type"] != "http" or scope.get("path") != "/api/growth/event":
            return await app(scope, receive, send_response)
        body = bytearray()
        header_names = {name for name, _ in scope.get("headers", [])}

        async def receive_body():
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
            return message

        async def record_response(message):
            if message["type"] == "http.response.start":
                payload = json.loads(body)
                receipt = {
                    "source": payload.get("source"), "action": payload.get("action"),
                    "status": message["status"],
                    "has_cookie": b"cookie" in header_names,
                    "has_referer": b"referer" in header_names,
                }
                with receipts_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(receipt) + "\n")
            await send_response(message)

        await app(scope, receive_body, record_response)

    uvicorn.run(observed_app, host="127.0.0.1", port=port)


def wait_for_browser_receipts(path):
    # All six requests must reach the server before analytics is deliberately
    # blocked. This also avoids racing the last document's keepalive request.
    deadline = time.monotonic() + 5
    receipts = []
    while time.monotonic() < deadline:
        if path.exists():
            receipts = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if len(receipts) >= 6:
            break
        time.sleep(.05)
    assert len(receipts) == 6, receipts
    expected = sorted(("path:" + slug, action) for slug, click, _ in PATHS
                      for action in ("view", click))
    assert sorted((item["source"], item["action"]) for item in receipts) == expected, receipts
    assert all(item["status"] == 204 for item in receipts), receipts
    assert all(not item["has_cookie"] and not item["has_referer"] for item in receipts), receipts


def exercise(browser, base, receipts_path):
    context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ru-RU")
    admin_context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ru-RU")
    page = context.new_page()
    admin = admin_context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    admin.on("pageerror", lambda error: errors.append(str(error)))
    try:
        # A real local login cookie exists, but the analytics fetch must omit it.
        checked(page.request.post(base + "/api/login", headers=HEADERS,
                                  data={"email": "kladovshik@demo.example",
                                        "password": "DemoPass2026!"}))
        assert context.cookies(), "Privacy test must run with a session cookie present"
        assert page.request.get(base + "/api/admin/growth").status == 403

        for slug, action, destination in PATHS:
            source = "path:" + slug
            with page.expect_response(lambda response: matches_event(response.request, source, "view")) as view:
                page.goto(base + "/journal/paths/" + slug + "?utm_source=private-test-marker",
                          wait_until="networkidle")
            assert view.value.status == 204
            request = view.value.request
            headers = request.all_headers()
            assert "cookie" not in headers, "Aggregate events must not carry a session cookie"
            assert "referer" not in headers, "Aggregate events must not carry the page URL"
            assert "private-test-marker" not in request.post_data
            assert set(request.post_data_json) == {"source", "action"}
            for width in (320, 390):
                page.set_viewport_size({"width": width, "height": 844})
                if page.locator("#reading-mode-toggle").get_attribute("aria-pressed") != "true":
                    page.locator("#reading-mode-toggle").click()
                expect(page.locator("body")).to_have_class(re.compile(r".*comfortable-view.*"))
                no_overflow(page)
            capture(page, "route-" + slug + "-mobile-large")
            # keepalive survives navigation, but Chromium need not deliver the
            # response event to Playwright after the old document is detached.
            # Observe the outgoing request here; the admin report below must
            # still prove that every CTA was persisted exactly once.
            with page.expect_request(lambda request: matches_event(request, source, action)) as click:
                page.locator(f'.jr-bottom a[data-growth-action="{action}"]').click()
            assert_destination(page, base, destination)
            assert click.value.post_data_json == {"source": source, "action": action}

        # Server-received headers remain authoritative when navigation detaches
        # the document that emitted a keepalive request.
        wait_for_browser_receipts(receipts_path)

        # Exercise all three recommendation directions through actual links.
        article_slug = "cifrovye-navyki-dlya-raboty"
        page.goto(base + "/journal/" + article_slug, wait_until="networkidle")
        job_card = page.locator(".jr-job-card").first
        expect(job_card).to_be_visible()
        job_path = job_card.get_attribute("href")
        job_source = "vacancy:" + job_path.rsplit("/", 1)[1]
        with page.expect_request(lambda request: matches_event(
                request, article_slug, "recommended_vacancy_click")):
            job_card.click()
        assert_destination(page, base, job_path)
        reading = page.locator(".reading-card").first
        expect(reading).to_be_visible()
        article_path = reading.get_attribute("href")
        with page.expect_request(lambda request: matches_event(
                request, job_source, "article_click")):
            reading.click()
        assert_destination(page, base, article_path)
        page.goto(base + job_path, wait_until="networkidle")
        company_path = page.locator('a[data-growth-action="company_click"]').first.get_attribute("href")
        page.goto(base + company_path, wait_until="networkidle")
        company_source = "company:" + company_path.rsplit("/", 1)[1]
        company_reading = page.locator(".employer-reading-card").first
        expect(company_reading).to_be_visible()
        company_article_path = company_reading.get_attribute("href")
        with page.expect_request(lambda request: matches_event(
                request, company_source, "article_click")):
            company_reading.click()
        assert_destination(page, base, company_article_path)
        page.wait_for_load_state("networkidle")
        expected_discovery = {
            (article_slug, "recommended_vacancy_click"),
            (job_source, "article_click"), (company_source, "article_click"),
        }
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            received = [
                json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()
            ]
            discovery_receipts = [
                item for item in received if (item["source"], item["action"]) in expected_discovery
            ]
            if len(discovery_receipts) >= 3:
                break
            time.sleep(.05)
        assert len(discovery_receipts) == 3, discovery_receipts
        assert {(item["source"], item["action"]) for item in discovery_receipts} == expected_discovery
        assert all(item["status"] == 204 and not item["has_cookie"] and not item["has_referer"]
                   for item in discovery_receipts)

        # A blocked analytics service must never interfere with ordinary links.
        def block_analytics(route):
            route.abort("failed")
        page.route("**/api/growth/event", block_analytics)
        for slug, action, destination in (PATHS[0], PATHS[2]):
            page.goto(base + "/journal/paths/" + slug, wait_until="networkidle")
            page.locator(f'.jr-bottom a[data-growth-action="{action}"]').click()
            assert_destination(page, base, destination)
        page.unroute("**/api/growth/event", block_analytics)

        checked(admin.request.post(base + "/api/login", headers=HEADERS,
                                   data={"email": "admin@demo.example", "password": "DemoPass2026!"}))
        dynamic_slug = "growth-test-new-editorial-guide"
        title = "Новая статья — разбор условий работы"
        created = checked(admin.request.post(base + "/api/admin/journal", headers=HEADERS, data={
            "slug": dynamic_slug, "title": title,
            "description": "Проверка новой опубликованной статьи в агрегированном административном отчёте.",
            "category": "Карьера", "read": "3 минуты",
            "body_text": (
                "## Сравните условия работы\n"
                "Составьте список вопросов о графике, задачах и составе оплаты. "
                "Попросите работодателя объяснить условия до принятия решения.\n\n"
                "## Выберите следующий шаг\n"
                "Сравните ответы с собственными ожиданиями и уточните оставшиеся детали. "
                "Для учебной проверки используются только вымышленные данные."
            ),
        }))
        checked(admin.request.post(base + "/api/admin/journal/" + dynamic_slug + "/publish",
                                   headers=HEADERS, data={"version": created["version"]}))
        # A click without a view is possible when requests are blocked or retried.
        send(admin, base, dynamic_slug, "profile_click")
        # The discovery flow may already have opened one of the seed articles.
        # Keep the 200% ratio fixture independent of recommendation ranking.
        visited_articles = {"/journal/" + article_slug, article_path, company_article_path}
        ratio_slug = next(
            slug for slug in ("sobesedovanie-posle-50", "kak-proverit-vakansiyu",
                              "proektnaya-rabota-posle-50", "rabotodatelyu-ocenit-opyt")
            if "/journal/" + slug not in visited_articles
        )
        send(admin, base, ratio_slug, "view")
        send(admin, base, ratio_slug, "jobs_click")
        send(admin, base, ratio_slug, "jobs_click")
        report = checked(admin.request.get(base + "/api/admin/growth?days=30"))
        assert report["summary"]["community_clicks"] == 1
        assert report["summary"]["journal_vacancy_clicks"] == 1
        assert report["summary"]["vacancy_article_clicks"] == 1
        assert report["summary"]["company_article_clicks"] == 1
        for slug, action, _ in PATHS:
            row = next(item for item in report["by_source"] if item["source"] == "path:" + slug)
            assert row["view"] == 1 and row[action] == 1, row
        assert all(value not in str(report) for value in (
            "kladovshik@demo.example", "Александр Демонстрационный", "+70000000001",
            "private-test-marker",
        ))

        admin.goto(base, wait_until="networkidle")
        expect(admin.locator("#admin-growth-stats")).to_contain_text("Переходы в сообщество")
        for label in ("Статья → карточка вакансии", "Вакансия → статья", "Компания → статья"):
            expect(admin.locator("#admin-growth-stats")).to_contain_text(label)
        rows = admin.locator("#admin-growth-articles tbody tr")
        expect(rows).to_have_count(len(report["by_source"]))
        for slug, _, _ in PATHS:
            expect(admin.locator(f'#admin-growth-articles tr[data-growth-source="path:{slug}"]')).to_have_count(1)
        dynamic_row = admin.locator(f'#admin-growth-articles tr[data-growth-source="{dynamic_slug}"]')
        expect(dynamic_row).to_contain_text(title)
        expect(dynamic_row.locator("td").last).to_have_text("—")
        ratio_row = admin.locator(f'#admin-growth-articles tr[data-growth-source="{ratio_slug}"]')
        expect(ratio_row.locator("td").last).to_have_text(re.compile(r"200(?:[.,]0)?\s*%"))
        expect(admin.locator("#admin-growth-articles")).to_contain_text("Может превышать 100%")
        capture(admin, "growth-report-desktop")
        for width in (320, 390):
            admin.set_viewport_size({"width": width, "height": 844})
            if admin.locator("#reading-mode-toggle").get_attribute("aria-pressed") != "true":
                admin.locator("#reading-mode-toggle").click()
            expect(admin.locator("body")).to_have_class(re.compile(r".*comfortable-view.*"))
            no_overflow(admin)
        capture(admin, "growth-report-mobile-large")
        # Explicit local reading selections, bookmarks and calendar filtering.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/journal/guide/personal", wait_until="networkidle")
        expect(page.locator("#jr-personal-controls")).to_be_visible()
        topic = page.locator('[data-jr-topic][value="technology"]')
        topic.check()
        material = page.locator('[data-jr-material="cifrovye-navyki-dlya-raboty"]')
        expect(material).to_be_visible()
        expect(page.locator('[data-jr-material="sobesedovanie-posle-50"]')).to_be_hidden()
        assert page.evaluate("localStorage.getItem('stazhno-reading-topics-v1')") is None
        page.locator("#jr-remember-topics").click()
        material.locator("[data-jr-save]").click()
        expect(material.locator("[data-jr-save]")).to_have_attribute("aria-pressed", "true")
        page.reload(wait_until="networkidle")
        expect(topic).to_be_checked()
        expect(material.locator("[data-jr-save]")).to_have_attribute("aria-pressed", "true")
        page.locator("#jr-personal-saved").check()
        expect(page.locator("[data-jr-material]:visible")).to_have_count(1)
        capture(page, "personal-reading-mobile")
        material.locator("a.jr-card").click()
        save = page.locator('[data-jr-save="cifrovye-navyki-dlya-raboty"]')
        expect(save).to_have_attribute("aria-pressed", "true")
        save.click()
        expect(save).to_have_attribute("aria-pressed", "false")
        page.goto(base + "/journal/guide/personal", wait_until="networkidle")
        page.locator("#jr-personal-saved").check()
        expect(page.locator("#jr-personal-empty")).to_be_visible()
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#jr-clear-reading").click()
        expect(topic).not_to_be_checked()
        assert page.evaluate("localStorage.getItem('stazhno-reading-topics-v1')") is None
        assert page.evaluate("localStorage.getItem('stazhno-reading-saved-v1')") is None
        if page.locator("#reading-mode-toggle").get_attribute("aria-pressed") != "true":
            page.locator("#reading-mode-toggle").click()
        page.set_viewport_size({"width": 320, "height": 844})
        capture(page, "personal-reading-mobile-large")
        # Synthetic events exist only in the isolated test DB.
        for slug, date, event_format in (("test-past-event", "2000-01-01", "offline"),
                                         ("test-future-event", "2099-01-01", "online")):
            payload = {
                "slug": slug, "title": "Тестовое мероприятие " + slug,
                "description": "Учебная проверка календаря профессиональных мероприятий.",
                "category": "Обучение", "read": "3 минуты", "content_type": "event",
                "event_date": date, "event_format": event_format, "source_name": "Тестовый организатор",
                "body_text": ("## Первый раздел программы\nОписание учебного примера и целей мероприятия. "
                              "Здесь нет действительного приглашения. Только тест.\n\n"
                              "## Второй раздел программы\nОписание формата и условий вымышленного события. "
                              "Этот материал создаётся только в изолированной базе тестирования."),
            }
            event = checked(admin.request.post(base + "/api/admin/journal", headers=HEADERS, data=payload))
            checked(admin.request.post(base + "/api/admin/journal/" + slug + "/publish",
                                       headers=HEADERS, data={"version": event["version"]}))
        page.goto(base + "/journal/guide/events", wait_until="networkidle")
        upcoming = page.locator('#jr-events-grid a[href="/journal/test-future-event"]')
        past = page.locator('#jr-events-grid a[href="/journal/test-past-event"]')
        expect(upcoming).to_be_visible()
        expect(past).to_be_hidden()
        page.locator("#jr-event-period").select_option("past")
        expect(past).to_be_visible()
        expect(upcoming).to_be_hidden()
        page.locator("#jr-event-format").select_option("online")
        expect(page.locator("#jr-event-empty")).to_be_visible()
        page.locator("#jr-event-period").select_option("all")
        expect(upcoming).to_be_visible()
        capture(page, "event-calendar-mobile-large")
        # Academy: interactive self-check, explicit completion, resume and reset.
        academy_requests = []
        def observe_academy(request):
            if request.method != "GET":
                academy_requests.append(request.url)
        page.on("request", observe_academy)
        page.goto(base + "/academy", wait_until="networkidle")
        expect(page.locator("h1")).to_contain_text("Новые навыки")
        expect(page.locator("#ac-learning")).to_be_visible()
        expect(page.locator('[data-ac-filter="all"]')).to_have_attribute("aria-pressed", "true")
        page.locator('[data-ac-filter="active"]').click()
        expect(page.locator("#ac-learning-empty")).to_contain_text("Нет начатых курсов")
        expect(page.locator(".ac-course-card:visible")).to_have_count(0)
        page.locator('[data-ac-show-all]').click()
        expect(page.locator('[data-ac-filter="all"]')).to_be_focused()
        page.locator('a[data-ac-start]').click()
        expect(page.locator("h1")).to_have_text("Искусственный интеллект с нуля")
        expect(page.locator("[data-ac-progress-label]")).to_contain_text("0 из 6")
        page.locator("[data-ac-resume]").click()
        expect(page.locator("#ac-quiz")).to_be_visible()
        capture(page, "academy-lesson-mobile-large")
        form = page.locator("#ac-quiz")
        form.locator('input[name="q1"][value="0"]').check()
        form.locator('input[name="q2"][value="2"]').check()
        form.locator('button[type="submit"]').click()
        expect(page.locator("#ac-quiz-result")).to_contain_text("1 из 2")
        expect(page.locator("[data-ac-progress-label]")).to_contain_text("0 из 6")
        form.locator('input[name="q1"][value="1"]').check()
        form.locator('button[type="submit"]').click()
        expect(page.locator("#ac-quiz-result")).to_contain_text("Урок пройден")
        expect(page.locator("[data-ac-progress-label]")).to_contain_text("1 из 6")
        page.reload(wait_until="networkidle")
        expect(page.locator("[data-ac-progress-label]")).to_contain_text("1 из 6")
        page.goto(base + "/academy/ai-basics", wait_until="networkidle")
        expect(page.locator("[data-ac-resume]")).to_have_attribute("href", "/academy/ai-basics/clear-prompts")
        expect(page.locator('[data-ac-lesson-state="what-ai-does"]')).to_contain_text("Пройден")
        capture(page, "academy-course-mobile-large")
        page.goto(base + "/academy", wait_until="networkidle")
        page.locator('[data-ac-filter="active"]').click()
        expect(page.locator('[data-ac-filter="active"]')).to_contain_text("(1)")
        expect(page.locator('a[data-ac-start]')).to_have_attribute("href", "/academy/ai-basics/clear-prompts")
        expect(page.locator('a[data-ac-start]')).to_contain_text("Продолжить обучение")
        capture(page, "academy-my-learning-mobile")
        for width in (360, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 844})
            assert page.locator("#ac-learning").evaluate(
                "(node) => node.scrollWidth <= node.clientWidth + 2"
            ), f"Learning controls overflow at {width}px"
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('a[data-ac-start]').click()
        assert page.url.endswith("/academy/ai-basics/clear-prompts")
        # Use fictional local progress for full-completion and revision handling.
        page.goto(base + "/academy", wait_until="networkidle")
        card = page.locator(".ac-course-card")
        revision = card.get_attribute("data-ac-revision")
        key = "stazhno-academy-v1:ai-basics:" + revision
        lessons = card.get_attribute("data-ac-lessons").split()
        page.evaluate("([key, lessons]) => localStorage.setItem(key, JSON.stringify([...lessons, 'unknown', lessons[0]]))",
                      [key, lessons])
        page.reload(wait_until="networkidle")
        page.locator('[data-ac-filter="complete"]').click()
        expect(page.locator('[data-ac-filter="complete"]')).to_contain_text("(1)")
        expect(page.locator('a[data-ac-start]')).to_have_attribute("href", "/academy/ai-basics")
        expect(page.locator('a[data-ac-start]')).to_contain_text("Повторить курс")
        page.evaluate("([key, lessons]) => {localStorage.setItem(key + '-old', JSON.stringify(lessons)); localStorage.setItem(key, '{broken');}",
                      [key, lessons])
        page.reload(wait_until="networkidle")
        expect(page.locator('[data-ac-filter="complete"]')).to_contain_text("(0)")
        page.locator('[data-ac-filter="active"]').click()
        expect(page.locator("#ac-learning-empty")).to_be_visible()
        # A second tab can update local progress without a page reload.
        other = context.new_page()
        try:
            other.goto(base + "/academy", wait_until="networkidle")
            other.evaluate("([key, lesson]) => localStorage.setItem(key, JSON.stringify([lesson]))", [key, lessons[0]])
            expect(page.locator('[data-ac-filter="active"]')).to_contain_text("(1)")
            expect(page.locator("#ac-learning-empty")).to_be_hidden()
        finally:
            other.close()
        restricted = browser.new_context(viewport={"width":390,"height":844}, locale="ru-RU")
        try:
            restricted.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked');}});")
            blocked = restricted.new_page()
            blocked.goto(base + "/academy", wait_until="networkidle")
            expect(blocked.locator("#ac-learning-storage")).to_be_visible()
            blocked.locator('[data-ac-filter="active"]').click()
            expect(blocked.locator("#ac-learning-empty")).to_contain_text("Прогресс недоступен")
            blocked.locator('[data-ac-show-all]').click()
            expect(blocked.locator("a[data-ac-start]")).to_be_visible()
        finally:
            restricted.close()
        # Read-only storage still shows previously saved progress, but must
        # warn that new results might not be saved.
        readonly = browser.new_context(viewport={"width":390,"height":844}, locale="ru-RU")
        try:
            readonly.add_init_script("""(() => {
                const saved = """ + json.dumps([key, lessons[0]]) + """;
                localStorage.setItem(saved[0], JSON.stringify([saved[1]]));
                const set = Storage.prototype.setItem;
                Storage.prototype.setItem = function(k, v) {
                    if (this === localStorage && k.startsWith('stazhno-academy-v1:'))
                        throw new DOMException('Read only', 'QuotaExceededError');
                    return set.call(this, k, v);
                };
            })();""")
            read_page = readonly.new_page()
            read_page.goto(base + "/academy", wait_until="networkidle")
            expect(read_page.locator("#ac-learning-storage")).to_be_visible()
            expect(read_page.locator('[data-ac-filter="active"]')).to_contain_text("(1)")
            expect(read_page.locator('a[data-ac-start]')).to_have_attribute("href", "/academy/ai-basics/clear-prompts")
        finally:
            readonly.close()
        # A small probe may fit even when the actual progress write fails.
        # Keep the diagnostic in the tab across navigation without storing answers.
        quota = browser.new_context(viewport={"width":390,"height":844}, locale="ru-RU")
        try:
            quota.add_init_script("""(() => {
                const set = Storage.prototype.setItem;
                Storage.prototype.setItem = function(k, v) {
                    if (this === localStorage && k.startsWith('stazhno-academy-v1:')
                        && k !== 'stazhno-academy-v1:storage-probe')
                        throw new DOMException('Quota exceeded', 'QuotaExceededError');
                    return set.call(this, k, v);
                };
            })();""")
            quota_page = quota.new_page()
            quota_page.goto(base + "/academy", wait_until="networkidle")
            expect(quota_page.locator("#ac-learning-storage")).to_be_hidden()
            quota_page.goto(base + "/academy/ai-basics/what-ai-does", wait_until="networkidle")
            quiz = quota_page.locator("#ac-quiz")
            quiz.locator('input[name="q1"][value="1"]').check()
            quiz.locator('input[name="q2"][value="2"]').check()
            quiz.locator('button[type="submit"]').click()
            expect(quota_page.locator("#ac-quiz-result")).to_contain_text("Браузер не сохранил прогресс")
            quota_page.goto(base + "/academy", wait_until="networkidle")
            expect(quota_page.locator("#ac-learning-storage")).to_be_visible()
            expect(quota_page.locator('[data-ac-filter="active"]')).to_contain_text("(0)")
            assert quota_page.evaluate("key => localStorage.getItem(key)", key) is None
            assert quota_page.evaluate("localStorage.getItem('stazhno-academy-v1:storage-probe')") is None
        finally:
            quota.close()
        no_script = browser.new_context(java_script_enabled=False)
        try:
            basic = no_script.new_page()
            basic.goto(base + "/academy", wait_until="load")
            expect(basic.locator("#ac-learning")).to_be_hidden()
            expect(basic.locator("a[data-ac-start]")).to_have_attribute("href", "/academy/ai-basics")
            basic.locator("a[data-ac-start]").click()
            expect(basic.locator("h1")).to_have_text("Искусственный интеллект с нуля")
        finally:
            no_script.close()
        page.goto(base + "/academy/ai-basics", wait_until="networkidle")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("[data-ac-reset]").click()
        expect(page.locator("[data-ac-progress-label]")).to_contain_text("0 из 6")
        expect(page.locator("[data-ac-resume]")).to_have_attribute("href", "/academy/ai-basics/what-ai-does")
        assert not academy_requests, academy_requests
        page.remove_listener("request", observe_academy)
        assert not errors, "Uncaught browser errors: " + " | ".join(errors)
    except Exception:
        for name, active in (("visitor", page), ("admin", admin)):
            if not active.is_closed():
                active.screenshot(path=str(OUTPUT / ("failure-" + name + ".png")), full_page=True)
        raise
    finally:
        context.close()
        admin_context.close()


def exercise_action_plans(browser, base):
    url = base + "/journal/paths/nayti-rabotu"
    context = browser.new_context(viewport={"width": 390, "height": 844}, locale="ru-RU")
    errors = []
    unexpected = []
    # Existing anonymous aggregate view counters are not part of local progress.
    # Do not change the separate growth report's fixture counts.
    context.route("**/api/growth/event", lambda route: route.fulfill(status=204))
    context.on("request", lambda request: unexpected.append(request.url)
               if request.method != "GET" and not request.url.endswith("/api/growth/event") else None)
    try:
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="networkidle")
        checks = page.locator("[data-jr-journey-check]")
        expect(checks).to_have_count(4)
        expect(page.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 0 из 4")
        prefix = "stazhno-journey-v1:nayti-rabotu:"
        old_step = checks.first.get_attribute("data-jr-journey-check")
        assert not page.evaluate("key => localStorage.getItem(key)", prefix + old_step)
        checks.nth(0).focus()
        checks.nth(0).press("Space")
        expect(checks.nth(0)).to_be_checked()
        expect(page.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 1 из 4")
        other = context.new_page()
        other.goto(url, wait_until="networkidle")
        expect(other.locator("[data-jr-journey-check]").first).to_be_checked()
        other.locator("[data-jr-journey-check]").nth(1).check()
        expect(checks.nth(1)).to_be_checked()
        expect(page.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 2 из 4")
        page.goto(base + "/journal/paths", wait_until="networkidle")
        card = page.locator('[data-jr-journey="nayti-rabotu"]')
        expect(card.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 2 из 4")
        expect(card.locator("[data-jr-journey-resume]")).to_have_attribute("href", "/journal/paths/nayti-rabotu#step-sobesedovanie-posle-50")
        expect(page.locator('[data-jr-journey="novye-navyki"] [data-jr-journey-count]')).to_have_text("Выполнено: 0 из 3")
        card.locator("[data-jr-journey-resume]").click()
        expect(page).to_have_url(url + "#step-sobesedovanie-posle-50")
        page.locator("[data-jr-journey-check]").nth(2).check()
        page.locator("[data-jr-journey-check]").nth(3).check()
        expect(page.locator("[data-jr-journey-resume]")).to_have_attribute("href", "#jr-journey-next")
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 844})
            if page.locator("#reading-mode-toggle").get_attribute("aria-pressed") != "true":
                page.locator("#reading-mode-toggle").click()
            no_overflow(page)
        capture(page, "journey-completed-large")
        page.locator("[data-jr-journey-reset]").click()
        expect(page.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 0 из 4")
        expect(other.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 0 из 4")
        assert page.evaluate("prefix => Object.keys(localStorage).filter(k=>k.startsWith(prefix))", prefix) == []
        page.evaluate("key => localStorage.setItem(key, 'invalid')", prefix + old_step)
        page.evaluate("key => localStorage.setItem(key, 'yes')", prefix + "obsolete:" + "f"*24)
        page.reload(wait_until="networkidle")
        expect(page.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 0 из 4")
        # Simulate an editorial revision while another tab keeps the older
        # rendered steps. Both ordinary changes and resetting in the stale
        # tab must preserve the current revision's mark.
        old_digest = old_step.split(":")[1]
        new_step = old_step.split(":")[0] + ":" + ("e"*24 if old_digest != "e"*24 else "d"*24)
        page.locator("[data-jr-journey-check]").first.check()
        def newer_revision(route):
            response = route.fetch()
            html = response.text()
            assert old_step in html
            route.fulfill(response=response, body=html.replace(old_step, new_step))
        other.route("**/journal/paths/nayti-rabotu", newer_revision)
        other.goto(url, wait_until="networkidle")
        expect(other.locator("[data-jr-journey-check]").first).not_to_be_checked()
        other.locator("[data-jr-journey-check]").first.check()
        page.locator("[data-jr-journey-check]").nth(1).check()
        expect(other.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 2 из 4")
        page.locator("[data-jr-journey-reset]").click()
        expect(other.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 1 из 4")
        expect(other.locator("[data-jr-journey-check]").first).to_be_checked()
        assert page.evaluate("key => localStorage.getItem(key)", prefix + new_step) == "yes"
        assert not unexpected, unexpected
        assert not errors, errors
    finally:
        context.close()

    restricted = browser.new_context(viewport={"width":390,"height":844}, locale="ru-RU")
    try:
        restricted.route("**/api/growth/event", lambda route: route.fulfill(status=204))
        restricted.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked');}});")
        page = restricted.new_page()
        page.goto(url, wait_until="networkidle")
        expect(page.locator("[data-jr-journey-warning]")).to_be_visible()
        page.locator("[data-jr-journey-check]").first.check()
        expect(page.locator("[data-jr-journey-count]")).to_have_text("Выполнено: 1 из 4")
        expect(page.locator("[data-jr-journey-warning]")).to_be_visible()
    finally:
        restricted.close()

    no_script = browser.new_context(java_script_enabled=False)
    try:
        page = no_script.new_page()
        page.goto(url, wait_until="load")
        expect(page.locator("[data-jr-journey-progress]")).to_be_hidden()
        expect(page.locator(".jr-journey-task")).to_have_count(4)
        expect(page.locator(".jr-journey-task").first).to_be_visible()
        expect(page.locator(".jr-path-step").first.locator('a').first).to_have_attribute("href", "/journal/kak-pokazat-opyt-v-profile")
    finally:
        no_script.close()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="stazhno-growth-smoke-") as temporary:
        env = dict(os.environ, OPYT50_DB_PATH=str(Path(temporary) / "growth.db"),
                   OPYT50_ENV="development", OPYT50_PREVIEW_SEED_DEMO="0",
                   OPYT50_COOKIE_SECURE="0", OPYT50_ADMIN_MFA_MODE="off",
                   OPYT50_MAIL_WORKER_ENABLED="0", OPYT50_SMTP_HOST="", OPYT50_MAIL_FROM="",
                   OPYT50_PUBLIC_URL="", OPYT50_PREVIEW_PASSWORD="", OPYT50_ALLOWED_HOSTS="")
        env.pop("DATABASE_URL", None)
        subprocess.run([sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        log_path = Path(temporary) / "uvicorn.log"
        receipts_path = Path(temporary) / "growth-receipts.jsonl"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve", str(port), str(receipts_path)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(80):
                    try:
                        with urlopen(base + "/api/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError("Local growth server did not become ready")
                with sync_playwright() as playwright:
                    options = {"headless": True, "args": ["--no-sandbox"]}
                    if os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
                        options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"]
                    browser = playwright.chromium.launch(**options)
                    try:
                        exercise_action_plans(browser, base)
                        exercise(browser, base, receipts_path)
                    finally:
                        browser.close()
            except Exception:
                log.flush()
                print(log_path.read_text(encoding="utf-8")[-8000:], file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
    print("Growth browser smoke PASSED: routes, privacy, blocked analytics, dynamic report, ratios and mobile large text")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--serve":
        serve_with_receipts(int(sys.argv[2]), Path(sys.argv[3]))
    else:
        main()
