import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient

from fakecspace.app import ADMINS
from fakecspace.app import app as fake_app
from serena import tables
from serena.admin_sessions import Sessions, token_hash
from serena.app import create_app
from serena.config import Settings
from serena.cspace.accounts import AccountRoles, has_role, parse_roles, role_name
from serena.store import Store

# The simulator's synthetic admin accounts (password = username): admin has the role in every museum, pahma-admin
# only in PAHMA, viewer in none.
CHANGES = {"X-Serena-Admin": "1"}


def login(user: str) -> tuple[str, str]:
    return user, ADMINS[user]


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make_app(store: Store, s3: Any, secretsmanager: Any, http: Any = None, **settings: Any) -> Any:
    options: dict[str, Any] = {"admin_cookie_secure": False, **settings}
    config = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, env_label="Test",
                      _env_file=None, **options)
    # The museum is the first label of the host name the simulator is called by (pahma.cspace.test).
    factory = http or (lambda tenant: TestClient(fake_app, base_url=TENANTS[tenant]))
    return create_app(config, store, s3=s3, secretsmanager=secretsmanager, cspace_http=factory)


@pytest.fixture
def app(store: Store, s3: Any, secretsmanager: Any) -> Any:
    built = make_app(store, s3, secretsmanager)
    built.state.admin.sessions.clock = Clock()
    return built


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app, base_url="http://testserver")


def sign_in(client: TestClient, museum: str = "pahma", user: str = "admin", password: str | None = None,
            headers: dict[str, str] | None = None) -> Any:
    name, real = login(user) if user in ADMINS else (user, "x")
    return client.post("/admin/v1/sessions", headers=CHANGES if headers is None else headers,
                       json={"museum": museum, "username": name, "password": real if password is None else password})


# --- roles

def test_role_names_as_collectionspace_stores_them() -> None:
    assert role_name("15", "Serena_Admin") == "ROLE_15_SERENA_ADMIN"
    assert role_name("15", "Serena Admin") == "ROLE_15_SERENA_ADMIN"
    assert role_name("15", "ROLE_15_SERENA_ADMIN") == "ROLE_15_SERENA_ADMIN"
    assert has_role(AccountRoles("15", ["ROLE_15_TENANT_READER", "role_15_serena_admin"]), "Serena_Admin")
    assert not has_role(AccountRoles("15", ["ROLE_16_SERENA_ADMIN"]), "Serena_Admin")  # another tenant's
    assert not has_role(AccountRoles("", ["ROLE_15_SERENA_ADMIN"]), "Serena_Admin")


def test_the_simulators_roles_differ_by_museum() -> None:
    def roles(museum: str, user: str) -> AccountRoles:
        response = TestClient(fake_app, base_url=TENANTS[museum]).get(
            "/cspace-services/accounts/0/accountroles", auth=login(user))
        return parse_roles(response.content)

    assert has_role(roles("pahma", "pahma-admin"), "Serena_Admin")
    assert not has_role(roles("bampfa", "pahma-admin"), "Serena_Admin")
    assert all(has_role(roles(m, "admin"), "Serena_Admin") for m in TENANTS)
    assert not has_role(roles("pahma", "viewer"), "Serena_Admin")


# --- sign-in

def test_museums_for_the_menu(client: TestClient) -> None:
    keys = [m["key"] for m in client.get("/admin/v1/museums").json()]
    assert sorted(keys) == sorted(TENANTS)


def test_sign_in(client: TestClient, store: Store) -> None:
    response = sign_in(client)
    assert response.status_code == 200
    assert response.json()["museum"] == "pahma" and response.json()["user"] == "admin"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("serena_admin_pahma=")
    for flag in ("HttpOnly", "Path=/admin", "SameSite=strict", "Max-Age=28800"):
        assert flag.lower() in cookie.lower()
    me = client.get("/admin/v1/me").json()
    assert me["environment"] == "Test" and [s["museum"] for s in me["sessions"]] == ["pahma"]
    token = response.cookies["serena_admin_pahma"]
    item = store.client.get_item(TableName=store.table(tables.ADMIN_SESSIONS), Key={"pk": {"S": token_hash(token)}})
    assert item["Item"]["user"]["S"] == "admin"
    rows = store.client.scan(TableName=store.table(tables.ADMIN_SESSIONS))["Items"]
    assert all(token not in str(row) for row in rows)  # only its hash is stored
    assert "password" not in str(rows).lower()


def test_cookies_are_secure_outside_a_local_stack(store: Store, s3: Any, secretsmanager: Any) -> None:
    secure = TestClient(make_app(store, s3, secretsmanager, admin_cookie_secure=True), base_url="https://testserver")
    assert "secure" in sign_in(secure).headers["set-cookie"].lower()


def test_wrong_password(client: TestClient, store: Store, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    wrong = "not-" + login("admin")[1]  # synthetic
    response = sign_in(client, password=wrong)
    assert response.status_code == 401 and "don't work" in response.json()["detail"]
    assert "set-cookie" not in response.headers
    assert store.client.scan(TableName=store.table(tables.AUDIT))["Items"] == []  # not audited by username
    logged = caplog.text + " ".join(str(vars(record)) for record in caplog.records)
    assert wrong not in logged and "'admin'" not in logged


def test_no_admin_role(client: TestClient) -> None:
    response = sign_in(client, user="viewer")
    assert response.status_code == 403 and "Serena_Admin" in response.json()["detail"]
    assert client.get("/admin/v1/me").json()["sessions"] == []


def test_the_role_is_per_museum(client: TestClient) -> None:
    assert sign_in(client, "bampfa", "pahma-admin").status_code == 403
    assert sign_in(client, "pahma", "pahma-admin").status_code == 200


def test_the_password_isnt_logged_when_it_works(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sign_in(client, user="pahma-admin")
    logged = caplog.text + " ".join(str(vars(record)) for record in caplog.records)
    assert "pahma-admin" not in logged  # neither the password nor (here equal to it) the username


def test_changes_need_the_apps_header(client: TestClient) -> None:
    assert sign_in(client, headers={}).status_code == 403
    assert sign_in(client, headers={"X-Serena-Admin": "yes"}).status_code == 403


@pytest.mark.parametrize("museum", ["nowhere", "PAHMA", "pahma; drop", ""])
def test_an_unknown_museum(client: TestClient, museum: str) -> None:
    assert sign_in(client, museum=museum).status_code in (404, 422)


def test_collectionspace_doesnt_answer(store: Store, s3: Any, secretsmanager: Any) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no answer", request=request)

    app = make_app(store, s3, secretsmanager, http=lambda tenant: httpx.Client(transport=httpx.MockTransport(down)))
    assert sign_in(TestClient(app)).status_code == 503


# --- sessions

def test_one_session_per_museum(client: TestClient) -> None:
    sign_in(client, "pahma")
    sign_in(client, "cinefiles")
    assert sorted(s["museum"] for s in client.get("/admin/v1/me").json()["sessions"]) == ["cinefiles", "pahma"]
    assert client.delete("/admin/v1/sessions/pahma", headers=CHANGES).status_code == 200
    assert [s["museum"] for s in client.get("/admin/v1/me").json()["sessions"]] == ["cinefiles"]
    assert client.delete("/admin/v1/sessions/pahma", headers=CHANGES).status_code == 401


def test_a_session_cant_be_used_for_another_museum(client: TestClient) -> None:
    response = sign_in(client, "pahma")
    client.cookies.set("serena_admin_cinefiles", response.cookies["serena_admin_pahma"])
    assert client.get("/admin/v1/museums/cinefiles/audit").status_code == 401


def test_idle_and_absolute_timeouts(app: Any, client: TestClient) -> None:
    clock = app.state.admin.sessions.clock
    sign_in(client)
    clock.now += 29 * 60
    assert client.get("/admin/v1/museums/pahma/audit").status_code == 200
    clock.now += 29 * 60  # active 29 minutes ago: still in
    assert client.get("/admin/v1/museums/pahma/audit").status_code == 200
    clock.now += 31 * 60
    assert client.get("/admin/v1/museums/pahma/audit").status_code == 401  # idle too long
    sign_in(client)
    for _ in range(17):  # active every 29 minutes, for more than 8 hours
        clock.now += 29 * 60
        last = client.get("/admin/v1/museums/pahma/audit").status_code
    assert last == 401


def test_sign_everyone_out(store: Store, s3: Any, secretsmanager: Any, app: Any) -> None:
    first, second, other = TestClient(app), TestClient(app), TestClient(app)
    sign_in(first)
    sign_in(second, user="pahma-admin")
    sign_in(other, "cinefiles")
    response = first.post("/admin/v1/museums/pahma/sign-out-all", headers=CHANGES)
    assert response.json()["sessions_ended"] == 2
    assert second.get("/admin/v1/me").json()["sessions"] == []
    assert first.get("/admin/v1/me").json()["sessions"] == []
    assert [s["museum"] for s in other.get("/admin/v1/me").json()["sessions"]] == ["cinefiles"]


def test_sessions_expire_from_the_table() -> None:
    table = tables.ADMIN_SESSIONS
    assert table.ttl_attribute == "expires_at" and table in tables.ALL
    assert Sessions.__init__.__defaults__ == (30, 8, Sessions.__init__.__defaults__[2])  # type: ignore[index]


# --- the audit log

def test_the_audit_log(client: TestClient) -> None:
    sign_in(client)
    client.post("/admin/v1/museums/pahma/sign-out-all", headers=CHANGES)
    sign_in(client)
    entries = client.get("/admin/v1/museums/pahma/audit").json()["entries"]
    assert [e["action"] for e in entries] == ["sign_in", "sign_out_all", "sign_in"]
    assert entries[1]["details"] == {"sessions": 1} and all(e["admin"] == "admin" for e in entries)
    assert "password" not in str(entries).lower()


def test_the_audit_log_is_per_museum(client: TestClient) -> None:
    sign_in(client, "pahma")
    sign_in(client, "cinefiles")
    entries = client.get("/admin/v1/museums/cinefiles/audit").json()["entries"]
    assert [e["tenant"] for e in entries] == ["cinefiles"]


def test_the_api_documentation(client: TestClient) -> None:
    assert client.get("/admin/v1/museums/pahma/etl-api.json").status_code == 401
    sign_in(client)
    response = client.get("/admin/v1/museums/pahma/etl-api.json")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert "/museums/{tenant}/runs" in response.json()["paths"]


# --- the built app

def test_the_built_app_is_served(store: Store, s3: Any, secretsmanager: Any, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>admin app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside")
    client = TestClient(make_app(store, s3, secretsmanager, admin_dist_dir=str(dist)))
    page = client.get("/admin/runs")
    assert page.text == "<html>admin app</html>" and "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/admin/assets/app.js").text == "console.log(1)"
    assert "outside" not in client.get("/admin/..%2Fsecret.txt").text
    assert client.get("/admin/v1/nothing").status_code == 404
    assert client.get("/admin/v1/museums").status_code == 200


def test_without_a_built_app_only_the_api(client: TestClient) -> None:
    assert client.get("/admin/runs").status_code == 404
