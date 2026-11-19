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
        assert client.get("/static/privacy.html").status_code == 404
        assert client.get("/static/terms.html").status_code == 404
        assert client.get("/static/consent.html").status_code == 404
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



def test_test_operator_has_invalid_registration_and_single_source_html():
    from app.legal_config import legal_profile, readiness_failures, render_template

    p = legal_profile()
    assert p["operator_name"] == "ИП Иванов Иван Иванович"
    assert p["status"] == "TEST_ONLY"
    assert p["privacy_email"].endswith(".invalid")
    assert "INN format or checksum invalid" in readiness_failures()
    assert "missing written legal and owner signoff" in readiness_failures()
    html = render_template(
        '<span>{{OPERATOR_NAME}}</span><span>{{OGRNIP}}</span><span>{{PRIVACY_EMAIL}}</span>'
    )
    assert p["ogrnip"] in html
    assert p["privacy_email"] in html
    assert "{{" not in html
    escaped = render_template("{{OPERATOR_NAME}}", {
        **p, "operator_name": "<script>alert('x')</script>",
    })
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


def test_registration_live_guard_blocks_sample_operator(monkeypatch, tmp_path):
    app = create_app(str(tmp_path / "legal-live-guard.sqlite"))
    with TestClient(app) as client:
        monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        response = client.post(
            "/api/register",
            json={
                "role": "candidate", "name": "Тестовый кандидат",
                "email": "test-candidate@example.invalid",
                "password": "SecureLocalTest2026!",
            },
            headers={"X-Requested-With": "OPYT50"},
        )
        assert response.status_code == 503
        assert "юридического утверждения" in response.text


def test_approved_terms_must_be_explicit_and_receipt_is_persisted(monkeypatch, tmp_path):
    import importlib
    from app.db import database
    from app.legal_config import legal_profile

    module = importlib.import_module("app.main")
    app = create_app(str(tmp_path / "terms-receipt.sqlite"))
    monkeypatch.setattr(module, "legal_approved", lambda: True)
    with TestClient(app) as client:
        body = {
            "role": "candidate", "name": "Тестовый кандидат",
            "email": "terms@example.invalid",
            "password": "SecureLocalTest2026!",
        }
        headers = {"X-Requested-With": "OPYT50"}
        assert client.post("/api/register", json=body, headers=headers).status_code == 422
        assert client.post("/api/register", json={
            **body, "terms_accepted": True, "terms_version": "obsolete-version",
        }, headers=headers).status_code == 422
        actual_version = legal_profile()["terms_version"]
        response = client.post("/api/register", json={
            **body, "terms_accepted": True, "terms_version": actual_version,
        }, headers=headers)
        assert response.status_code == 201, response.text
        with database(app.state.db_path) as db:
            record = db.execute(
                "SELECT user_id,terms_version,privacy_version,accepted_at,evidence_method "
                "FROM legal_acceptance_records"
            ).fetchone()
            assert record is not None
            assert record["terms_version"] == actual_version
            assert record["privacy_version"] == legal_profile()["privacy_version"]
            assert record["evidence_method"] == "explicit-checkbox"
            assert record["accepted_at"]



def test_real_production_cannot_disable_legal_gate_with_pytest_marker(monkeypatch, tmp_path):
    app = create_app(str(tmp_path / "no-bypass.sqlite"))
    with TestClient(app) as client:
        # After startup so the unrelated production TLS/MFA settings stay out of
        # this focused regression test. Request-time production guard is real.
        monkeypatch.setenv("OPYT50_ENV", "production")
        monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "not-a-real-test-marker")
        response = client.post(
            "/api/register",
            headers={"X-Requested-With": "OPYT50"},
            json={
                "role": "candidate",
                "name": "Тестовая регистрация",
                "email": "blocked@example.invalid",
                "password": "SecureLocalPassword2026!",
            },
        )
        assert response.status_code == 503, response.text
