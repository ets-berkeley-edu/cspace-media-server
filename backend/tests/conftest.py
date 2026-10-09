import pytest

from serena.config import Settings

# Synthetic: no real server is called in the tests.
TENANTS = {key: f"https://{key}.cspace.test" for key in ("bampfa", "botgarden", "cinefiles", "pahma", "ucjeps")}


@pytest.fixture
def settings() -> Settings:
    return Settings(tenants=TENANTS, env_label="Test", _env_file=None)
