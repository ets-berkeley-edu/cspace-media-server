"""An admin's own CollectionSpace account, at sign-in (design: Admin web app, Sign-in; decided October 10, 2026).

The admin's username and password are sent once, to the museum's CollectionSpace they chose, to read the account's
roles (GET accounts/0/accountroles). The password is used for that one request and never kept, logged or stored."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from defusedxml import ElementTree

from .client import SERVICES, CSpaceError, CSpaceUnavailable

ROLES_PATH = "/accounts/0/accountroles"


@dataclass(frozen=True)
class AccountRoles:
    """The account's tenant ID and role names, e.g. ("15", ["ROLE_15_TENANT_READER", "ROLE_15_SERENA_ADMIN"])."""

    tenant_id: str = ""
    role_names: list[str] = field(default_factory=list)


def role_name(tenant_id: str, display_name: str) -> str:
    """The roleName CollectionSpace stores for a role created with this display name, as the BMU works it out: the
    display name upper-cased, spaces to underscores, other characters dropped, repeated underscores collapsed, then
    ROLE_<tenantId>_ added. "Serena_Admin" in tenant 15 is ROLE_15_SERENA_ADMIN."""
    name = re.sub(r"_+", "_", re.sub(r"[^A-Z0-9_]", "", display_name.upper().replace(" ", "_")))
    prefix = f"ROLE_{tenant_id}_"
    return name if name.startswith(prefix) else prefix + name


def has_role(roles: AccountRoles, display_name: str) -> bool:
    if not roles.tenant_id:
        return False
    wanted = role_name(roles.tenant_id, display_name).upper()
    return any(name.strip().upper() == wanted for name in roles.role_names)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_roles(xml: bytes) -> AccountRoles:
    root = ElementTree.fromstring(xml)
    tenant = next((el.text or "" for el in root.iter() if _local(el.tag) == "tenantId"), "").strip()
    names = [(el.text or "").strip() for el in root.iter() if _local(el.tag) == "roleName" and (el.text or "").strip()]
    return AccountRoles(tenant, names)


def account_roles(http: httpx.Client, base_url: str, username: str, password: str) -> AccountRoles:
    """The account's roles. CSpaceError(status=401) for a wrong username or password; CSpaceUnavailable if
    CollectionSpace doesn't answer. No retries: the admin can sign in again."""
    url = base_url.rstrip("/") + SERVICES + ROLES_PATH
    try:
        response = http.get(url, auth=httpx.BasicAuth(username, password), headers={"User-Agent": "serena-admin"})
    except httpx.TransportError as error:
        raise CSpaceUnavailable(f"GET {ROLES_PATH}: {type(error).__name__}") from error
    if response.status_code in (502, 503, 504):
        raise CSpaceUnavailable(f"GET {ROLES_PATH}: {response.status_code}")
    if response.status_code != 200:
        raise CSpaceError(f"GET {ROLES_PATH} returned {response.status_code}", response.status_code)
    try:
        return parse_roles(response.content)
    except ElementTree.ParseError as error:
        raise CSpaceError(f"GET {ROLES_PATH}: the answer isn't XML") from error
