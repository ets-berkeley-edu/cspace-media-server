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


def test_an_address_that_matches_nothing_gets_a_plain_not_found(settings: Settings, store: Store) -> None:
    """A short plain-text 404 outside Serena's APIs (Richard, October 14, 2026): never JSON, never a list of routes;
    the admin API keeps its JSON errors."""
    client = TestClient(create_app(settings, store))
    for path in ("/nowhere", "/local-cdn/pahma/objects", "/local-cdn/pahma/objects/abc", "/unavailable/nowhere.svg",
                 "/pahma"):
        answer = client.get(path)
        assert (answer.status_code, answer.text) == (404, "Not found."), path
        assert answer.headers["content-type"].startswith("text/plain")
        assert answer.headers["cache-control"] == "no-store"
    admin = client.get("/admin/v1/nowhere")
    assert admin.status_code == 404 and admin.json() == {"detail": "Not Found"}
