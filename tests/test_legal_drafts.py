"""Legal IP draft previews and fail-closed release readiness.

This test does not claim legality or replace lawyer-reviewed documents.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from scripts.check_legal_readiness import verify


def test_ip_legal_pages_are_readonly_and_explicitly_unapproved(tmp_path):
    app = create_app(str(tmp_path / "legal-previews.sqlite"))
    with TestClient(app) as client:
        for path, title in (
            ("/privacy", "Политика обработки персональных данных"),
            ("/terms", "Пользовательское соглашение"),
            ("/legal/consent", "Согласия и подтверждения"),
        ):
            res = client.get(path)
            assert res.status_code == 200, (path, res.text)
            assert "text/html" in res.headers["content-type"]
            assert res.headers.get("x-robots-tag") == "noindex, nofollow"
            assert "no-store" in res.headers.get("cache-control", "")
            assert 'name="robots" content="noindex,nofollow"' in res.text
            assert "Иванов Иван Иванович" in res.text
            assert title in res.text
            assert "ТЕСТОВЫЕ ДАННЫЕ" in res.text
            assert client.post(path).status_code == 405
        assert client.get("/static/legal.css").status_code == 200
        assert client.get("/static/legal-notice.css").status_code == 200


def test_registration_and_footer_link_drafts_without_claiming_consent(tmp_path):
    app = create_app(str(tmp_path / "legal-home.sqlite"))
    with TestClient(app) as client:
        html = client.get("/").text
        assert 'href="/privacy"' in html
        assert 'href="/terms"' in html
        assert 'href="/legal/consent"' in html
        assert 'id="auth-legal-notice"' in html
        assert 'id="legal-operator-info"' in html
        assert "ТЕСТОВЫЕ ДАННЫЕ" in html
        assert "НЕ ПОДТВЕРЖДЕНЫ" in html


def test_public_release_legal_gate_fails_on_placeholder_drafts():
    root = Path(__file__).resolve().parents[1]
    checks = verify(root)
    failed = {name for name, ok, _ in checks if not ok}
    # DRAFT pages are *not* legally compliant documents.
    assert "Public privacy-policy page" in failed
    assert "Public user-terms page" in failed
    assert "Legal information near registration" in failed
    assert "Visible operator identification" in failed
    assert "Verified IP operator profile" in failed
    assert "Human legal release signoff" in failed
