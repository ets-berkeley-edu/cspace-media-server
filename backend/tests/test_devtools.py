import json
from typing import Any

import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient

from devtools import fake_etl
from devtools.seed import seed
from fakecspace.app import app as fake_app
from fakecspace.app import store as fake
from serena import museum
from serena.app import create_app
from serena.config import Settings
from serena.museum_settings import MuseumSettings
from serena.runs import Runs
from serena.store import Store
from serena.worker import Worker, WorkerServices


@pytest.fixture(autouse=True)
def reset_fake() -> Any:
    fake.reset()
    yield
    fake.reset()


def local_settings() -> Settings:
    """As docker-compose.yml sets them, with moto in-process instead of its container."""
    ids = {t: f"serena/local/{t}" for t in TENANTS}
    return Settings(tenants={t: "http://fakecspace" for t in TENANTS}, table_prefix="t",
                    buckets={t: f"serena-local-{t}" for t in TENANTS},
                    etl_token_secret_ids={t: f"{ids[t]}/etl-tokens" for t in TENANTS},
                    cspace_secret_ids={t: f"{ids[t]}/cspace" for t in TENANTS},
                    signing_key_secret_ids={"cinefiles": "serena/local/cinefiles/pdf-signing-key"},
                    local_cdn=True, dynamodb_endpoint="http://moto:5000", worker_poll_seconds=0, _env_file=None)


def test_seed_makes_buckets_and_secrets(s3: Any, secretsmanager: Any) -> None:
    settings = local_settings()
    done = seed(settings, s3, secretsmanager)
    assert sorted(done["buckets"]) == sorted(settings.buckets.values())
    assert len(done["secrets"]) == 2 * len(TENANTS) + 1
    tokens = {t: json.loads(secretsmanager.get_secret_value(SecretId=i)["SecretString"])["current"]
              for t, i in settings.etl_token_secret_ids.items()}
    assert len(set(tokens.values())) == len(TENANTS) and all(len(t) >= 32 for t in tokens.values())
    key = json.loads(secretsmanager.get_secret_value(SecretId="serena/local/cinefiles/pdf-signing-key")["SecretString"])
    assert key["current"]["kid"] == "local-cinefiles" and len(key["current"]["key"]) >= 32
    assert seed(settings, s3, secretsmanager) == {"buckets": [], "secrets": []}  # a second run changes nothing
    again = json.loads(secretsmanager.get_secret_value(SecretId=settings.etl_token_secret_ids["pahma"])["SecretString"])
    assert again["current"] == tokens["pahma"]


def test_the_fake_etls_file_is_the_same_every_night() -> None:
    assert fake_etl.tsv(fake_etl.rows("pahma", 5)) == fake_etl.tsv(fake_etl.rows("pahma", 5))
    assert fake_etl.rows("pahma", 5) != fake_etl.rows("bampfa", 5)
    kinds = {kind for _, _, kind, _ in fake_etl.rows("cinefiles", 6)}
    assert kinds == {"image", "pdf"}


@pytest.fixture
def stack(store: Store, s3: Any, secretsmanager: Any, dynamodb: Any) -> Any:
    settings = local_settings()
    seed(settings, s3, secretsmanager)
    app = create_app(settings, store, s3=s3, secretsmanager=secretsmanager,
                     cspace_http=lambda tenant: TestClient(fake_app, base_url="http://fakecspace"))
    services = WorkerServices(settings, museum.load_all(settings.tenants), MuseumSettings(store, 0), Runs(store),
                              store, s3)
    worker = Worker(services, sleep=lambda seconds: None)

    def token(tenant: str) -> str:
        secret: str = json.loads(secretsmanager.get_secret_value(
            SecretId=settings.etl_token_secret_ids[tenant])["SecretString"])["current"]
        return secret

    return TestClient(app, follow_redirects=False), TestClient(fake_app), worker, token


def test_a_whole_night_then_a_file_is_fetched_and_served(stack: Any) -> None:
    serena, cspace, worker, token = stack
    summary = fake_etl.night(serena, cspace, "pahma", token("pahma"), count=6, poll=0,
                             wait=lambda seconds: worker.tick())
    assert summary["state"] == "applied"
    assert summary["preflight"]["result"] == "passed"
    assert summary["apply"]["written"] == 6
    response = serena.get(summary["samples"]["image"])
    assert response.status_code == 302 and response.headers["location"].startswith("/local-cdn/pahma/objects/")
    assert serena.get(response.headers["location"]).status_code == 200
    # The next night, the same file: no rows change.
    again = fake_etl.night(serena, cspace, "pahma", token("pahma"), count=6, poll=0, wait=lambda s: worker.tick())
    assert again["state"] == "applied" and again["preflight"]["added"] == 0


def test_a_partial_night_stops_after_the_preflight(stack: Any) -> None:
    serena, cspace, worker, token = stack
    summary = fake_etl.night(serena, cspace, "cinefiles", token("cinefiles"), count=6, partial=True, poll=0,
                             wait=lambda seconds: worker.tick())
    assert summary["state"] == "ready" and summary["apply"] is None
    assert "pdf (restricted)" in summary["samples"]
