from fastapi.testclient import TestClient

from serena.app import create_app
from serena.config import Settings
from serena.store import Store


def test_health_answers_ok_and_nothing_more(settings: Settings, store: Store) -> None:
    client = TestClient(create_app(settings, store))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["cache-control"] == "no-store"


def test_no_interactive_api_documentation(settings: Settings, store: Store) -> None:
    client = TestClient(create_app(settings, store))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_the_app_loads_the_deployments_museums(settings: Settings, store: Store) -> None:
    app = create_app(settings, store)
    assert sorted(app.state.museums) == ["bampfa", "botgarden", "cinefiles", "pahma", "ucjeps"]
