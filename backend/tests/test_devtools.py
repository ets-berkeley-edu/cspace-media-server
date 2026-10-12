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
from serena.refreshes import Refreshes
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
    assert seed(settings, s3, secretsmanager) == {"buckets": [], "secrets": []}  # a second seed changes nothing
    again = json.loads(secretsmanager.get_secret_value(SecretId=settings.etl_token_secret_ids["pahma"])["SecretString"])
    assert again["current"] == tokens["pahma"]


def test_the_fake_etls_file_is_the_same_every_day() -> None:
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
    services = WorkerServices(settings, museum.load_all(settings.tenants), MuseumSettings(store, 0), Refreshes(store),
                              store, s3)
    worker = Worker(services, sleep=lambda seconds: None)

    def token(tenant: str) -> str:
        secret: str = json.loads(secretsmanager.get_secret_value(
            SecretId=settings.etl_token_secret_ids[tenant])["SecretString"])["current"]
        return secret

    return TestClient(app, follow_redirects=False), TestClient(fake_app), worker, token


def test_a_whole_day_then_a_file_is_fetched_and_served(stack: Any) -> None:
    serena, cspace, worker, token = stack
    summary = fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), count=6, poll=0,
                             wait=lambda seconds: worker.tick())
    assert summary["state"] == "updated"
    assert summary["check"]["result"] == "passed"
    assert summary["update"]["written"] == 7  # and PAHMA's restricted-image Blob
    assert not any("restricted-image" in warning for warning in summary["check"]["warnings"])
    response = serena.get(summary["samples"]["image"])
    assert response.status_code == 302 and response.headers["location"].startswith("/local-cdn/pahma/objects/")
    assert serena.get(response.headers["location"]).status_code == 200
    # The next day, the same servable list: no rows change.
    again = fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), count=6, poll=0,
                                   wait=lambda s: worker.tick())
    assert again["state"] == "updated" and again["check"]["added"] == 0


def test_a_failed_refresh_never_calls_serena(stack: Any) -> None:
    """--failed (D85): the simulator's records and the servable list are made, but Serena isn't called, as when it
    can't be reached; the repair is an admin refresh."""
    serena, cspace, worker, token = stack
    summary = fake_etl.daily_refresh(serena, cspace, "cinefiles", token("cinefiles"), count=6, failed=True, poll=0,
                                     wait=lambda seconds: worker.tick())
    assert summary["state"] is None and summary["refresh_id"] is None
    assert "pdf (restricted)" in summary["samples"]
    headers = {"Authorization": f"Bearer {token('cinefiles')}"}
    assert serena.get("/etl/v1/museums/cinefiles", headers=headers).status_code == 404  # no refresh at all


def test_a_day_with_different_rows_trips_the_threshold(stack: Any) -> None:
    """What happens when ./serena etl pahma --rows 3 follows a 20-row refresh: the servable list check
    refuses, as it should. Rerunning the ETL job with the right list repairs the same refresh."""
    serena, cspace, worker, token = stack
    tick = lambda seconds: worker.tick()  # noqa: E731
    assert fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), poll=0, wait=tick)["state"] == "updated"
    smaller = fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), count=3, poll=0, wait=tick)
    assert smaller["state"] == "check_failed" and fake_etl.threshold_failed(smaller)
    assert fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), poll=0, wait=tick)["state"] == "updated"


def test_the_counts_are_printed(stack: Any) -> None:
    """./serena etl prints the rows and counts the admin app shows, so a check needs no browser."""
    serena, cspace, worker, token = stack
    tick = lambda seconds: worker.tick()  # noqa: E731
    first = fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), poll=0, wait=tick)
    assert fake_etl.count_lines(first) == ["  servable list: 21 rows",
                                           "  servability update: 21 written, 0 deleted, 0 unchanged"]
    smaller = fake_etl.daily_refresh(serena, cspace, "pahma", token("pahma"), count=3, poll=0, wait=tick)
    assert fake_etl.count_lines(smaller) == [
        "  servable list: 4 rows; 0 added, 17 removed, 0 changed (80.95% of the last servability update's 21 rows)"]
    assert fake_etl.count_lines({"refresh_id": None, "state": None, "check": None, "update": None}) == []


def test_the_restricted_image_blob_is_listed_without_a_media_csid() -> None:
    listed = fake_etl.rows("pahma", 2)
    assert listed[-1][0] == "59a733dd-d641-4e1a-8552" and listed[-1][1] == ""
    assert all(row[1] for row in fake_etl.rows("bampfa", 2))  # no restricted-image Blob there



def test_file_only_prints_the_days_file_for_the_upload_page(monkeypatch: pytest.MonkeyPatch,
                                                              capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    class Local:
        secretsmanager_endpoint = "http://moto:5000"

    monkeypatch.setattr(fake_etl, "get_settings", lambda: Local())
    monkeypatch.setattr("devtools.fake_etl.httpx.Client", lambda **kwargs: TestClient(fake_app))
    monkeypatch.setattr("sys.argv", ["fake_etl", "--museum", "bampfa", "--rows", "3", "--file-only"])
    fake_etl.main()
    assert capsysbinary.readouterr().out == fake_etl.tsv(fake_etl.rows("bampfa", 3))
    media = fake_etl.rows("bampfa", 3)[0][1]
    assert media in fake.media  # added to the simulator, so its files can be fetched
