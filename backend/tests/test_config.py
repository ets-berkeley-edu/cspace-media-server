import pytest
from pydantic import ValidationError

from serena.config import Settings


def test_tenants_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERENA_TENANTS", '{"pahma": "https://pahma.cspace.test/"}')
    settings = Settings(_env_file=None)
    assert settings.tenants == {"pahma": "https://pahma.cspace.test"}


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.tenants == {}
    assert settings.log_level == "INFO"


def test_a_collectionspace_server_must_be_a_url() -> None:
    with pytest.raises(ValidationError, match="http"):
        Settings(tenants={"pahma": "pahma.cspace.test"}, _env_file=None)
