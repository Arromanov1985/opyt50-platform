"""Read-only screenshots of the public Timeweb homepage for visual review.

No login, personal profiles, passwords, API mutations or background actions.
This diagnostic never blocks PR CI when the external preview is inaccessible.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = os.getenv(
    "STAZHNO_PREVIEW_URL",
    "https://arromanov1985-opyt50-platform-fdd8.twc1.net",
).rstrip("/")
OUTPUT = Path(os.getenv("STAZHNO_TIMEWEB_REVIEW_DIR", "timeweb-public-review"))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"url": URL, "public_only": True, "screens": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for label, width, height in (
                ("desktop", 1366, 900),
                ("mobile", 390, 844),
            ):
                row = {"viewport": label, "width": width, "height": height}
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    locale="ru-RU",
                )
                try:
                    page = context.new_page()
                    response = page.goto(URL + "/", wait_until="domcontentloaded", timeout=25000)
                    row["http_status"] = response.status if response else None
                    if response is None or response.status != 200:
                        row["result"] = "not-captured"
                    else:
                        try:
                            page.wait_for_load_state("networkidle", timeout=12000)
                        except Exception:
                            pass  # A live page may have ongoing polling.
                        page.screenshot(
                            path=str(OUTPUT / f"timeweb-{label}.png"), full_page=True
                        )
                        row["title"] = page.title()
                        row["result"] = "captured"
                        row["horizontal_overflow"] = page.evaluate("""() => (
                          document.documentElement.scrollWidth > document.documentElement.clientWidth + 3
                        )""")
                except Exception as error:
                    row["result"] = "capture-error"
                    row["error_type"] = type(error).__name__
                finally:
                    report["screens"].append(row)
                    context.close()
        finally:
            browser.close()
    (OUTPUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
