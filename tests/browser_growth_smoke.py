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
    assert dimensions["document"] <= dimensions["viewport"] + 2, dimensions


def capture(page, name):
    no_overflow(page)
    page.screenshot(path=str(OUTPUT / (name + ".png")), full_page=True)


def matches_event(request, source, action):
    return (request.url.endswith("/api/growth/event") and request.method == "POST"
            and request.post_data_json == {"source": source, "action": action})


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
            expect(page).to_have_url(base + destination)
            assert click.value.post_data_json == {"source": source, "action": action}

        # Server-received headers remain authoritative when navigation detaches
        # the document that emitted a keepalive request.
        wait_for_browser_receipts(receipts_path)

        # A blocked analytics service must never interfere with ordinary links.
        def block_analytics(route):
            route.abort("failed")
        page.route("**/api/growth/event", block_analytics)
        for slug, action, destination in (PATHS[0], PATHS[2]):
            page.goto(base + "/journal/paths/" + slug, wait_until="networkidle")
            page.locator(f'.jr-bottom a[data-growth-action="{action}"]').click()
            expect(page).to_have_url(base + destination)
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
        ratio_slug = "sobesedovanie-posle-50"
        send(admin, base, ratio_slug, "view")
        send(admin, base, ratio_slug, "jobs_click")
        send(admin, base, ratio_slug, "jobs_click")
        report = checked(admin.request.get(base + "/api/admin/growth?days=30"))
        assert report["summary"]["community_clicks"] == 1
        for slug, action, _ in PATHS:
            row = next(item for item in report["by_source"] if item["source"] == "path:" + slug)
            assert row["view"] == 1 and row[action] == 1, row
        assert all(value not in str(report) for value in (
            "kladovshik@demo.example", "Александр Демонстрационный", "+70000000001",
            "private-test-marker",
        ))

        admin.goto(base, wait_until="networkidle")
        expect(admin.locator("#admin-growth-stats")).to_contain_text("Переходы в сообщество")
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
        assert not errors, "Uncaught browser errors: " + " | ".join(errors)
    except Exception:
        for name, active in (("visitor", page), ("admin", admin)):
            if not active.is_closed():
                active.screenshot(path=str(OUTPUT / ("failure-" + name + ".png")), full_page=True)
        raise
    finally:
        context.close()
        admin_context.close()


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
