from fastapi.testclient import TestClient

from serena.app import create_app
from serena.config import Settings


def test_health_answers_ok_and_nothing_more(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["cache-control"] == "no-store"


def test_no_interactive_api_documentation(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_the_app_loads_the_deployments_museums(settings: Settings) -> None:
    app = create_app(settings)
    assert sorted(app.state.museums) == ["bampfa", "botgarden", "cinefiles", "pahma", "ucjeps"]
