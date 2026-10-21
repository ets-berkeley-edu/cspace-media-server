"""The AWS tests' fixtures: the target environment, the admin app's address there, and the fake ETL's refresh.

serenade/conftest.py still applies (the browser, failure screenshots, @pytest.mark.after); this file replaces its
base_url (the local stack only) with the environment's admin app. The local tests never run here, and these never
run locally (serenade/conftest.py: collect_ignore)."""
from __future__ import annotations

import os
from typing import Any

import pytest

from serenade.aws.target import Target, fake_etl, from_environment, serena_aws

TARGET = from_environment()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "changes: changes the environment and undoes it; personal-dev only (D227)")
    config.addinivalue_line("markers", "simulator: needs the simulated CollectionSpace and the fake ETL")


def pytest_runtest_setup(item: pytest.Item) -> None:
    # Against a real CollectionSpace (QA), only the tests that look (D224, D227).
    if not TARGET.simulated:
        for marker in ("changes", "simulator"):
            if item.get_closest_marker(marker):
                pytest.skip(f"'{TARGET.env}' uses a real CollectionSpace: look-only tests only")


@pytest.fixture(scope="session")
def target() -> Target:
    return TARGET


@pytest.fixture(scope="session")
def base_url() -> str:
    """The environment's admin app (overrides serenade/conftest.py's local one)."""
    return TARGET.admin_url


@pytest.fixture(scope="session")
def admin() -> tuple[str, str]:
    """The admin account (D228): the simulator's admin/admin, or SERENADE_ADMIN_USER and SERENADE_ADMIN_PASSWORD,
    which ./serena aws test requires against a real CollectionSpace. Never written anywhere."""
    return os.environ["SERENADE_ADMIN_USER"], os.environ["SERENADE_ADMIN_PASSWORD"]


@pytest.fixture(scope="session")
def refresh() -> dict[str, Any]:
    """The run's daily refresh, by the fake ETL inside the environment (D226). A deploy or pause empties the simulator,
    and the refresh adds its records again, so every later test finds them."""
    if not TARGET.simulated:
        pytest.skip("no fake ETL against a real CollectionSpace")
    return fake_etl(TARGET.museum)


@pytest.fixture(scope="session")
def sample(target: Target, request: pytest.FixtureRequest) -> str:
    """An image Serena may serve, as its address: the refresh's sample (personal-dev), or the first image
    ./serena aws list shows (a real CollectionSpace, D226)."""
    if target.simulated:
        summary: dict[str, Any] = request.getfixturevalue("refresh")
        return target.url + str(summary["samples"]["image"])
    for line in serena_aws("list", target.museum, "--kind", "image", "--limit", "5").splitlines():
        words = line.split()
        if words and words[0] == "image" and words[1] == "public":
            return words[-1]
    pytest.skip(f"Serena has no public image for {target.museum} yet")
