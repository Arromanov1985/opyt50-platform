"""Taxonomy API and autocomplete source tests."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_taxonomy_api_exposes_shared_profession_and_skill_dictionary(tmp_path):
    app = create_app(str(tmp_path / "taxonomy.db"))
    with TestClient(app) as client:
        response = client.get("/api/taxonomy")
        assert response.status_code == 200
        data = response.json()

    profession_values = {item["value"] for item in data["professions"]}
    skill_values = {item["value"] for item in data["skills"]}

    assert "Территориальный менеджер" in profession_values
    assert "Региональный менеджер по продажам B2B" in profession_values
    assert "Excel" in skill_values
    assert "CRM" in skill_values
    assert "Битрикс24" in skill_values

    territorial = next(item for item in data["professions"] if item["value"] == "Территориальный менеджер")
    assert territorial["family"] == "региональные продажи"

    excel = next(item for item in data["skills"] if item["value"] == "Excel")
    assert "Microsoft Excel" in excel["aliases"]
