from typing import Any

import pytest
from pydantic import ValidationError

from serena import museum

ALL = ("Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg")


def test_every_museum_has_a_file() -> None:
    assert museum.available() == ["bampfa", "botgarden", "cinefiles", "pahma", "ucjeps"]


@pytest.mark.parametrize(
    ("key", "derivatives", "original"),
    [  # design: URLs, each museum's list of derivatives (decided October 9, 2026)
        ("bampfa", ("Thumbnail", "Medium"), False),
        ("botgarden", ("Thumbnail", "Medium", "OriginalJpeg"), False),
        ("cinefiles", ALL, True),
        ("pahma", ALL, True),
        ("ucjeps", ALL, True),
    ],
)
def test_derivatives_match_the_design(key: str, derivatives: tuple[str, ...], original: bool) -> None:
    config = museum.load(key)
    assert config.key == key
    assert config.derivatives == derivatives
    assert config.original is original


def test_only_pahma_has_a_restricted_image_blob() -> None:
    blobs = {key: museum.load(key).restricted_image_blob_csid for key in museum.available()}
    assert blobs == {"bampfa": None, "botgarden": None, "cinefiles": None, "pahma": "59a733dd-d641-4e1a-8552",
                     "ucjeps": None}


@pytest.mark.parametrize("key", ["bampfa", "botgarden", "cinefiles", "pahma", "ucjeps"])
def test_starting_settings(key: str) -> None:
    settings = museum.load(key).settings
    assert settings.watchdog_deadline == "08:00"
    assert (settings.etl_poll_interval_seconds, settings.etl_step_timeout_seconds) == (15, 1800)
    assert settings.change_threshold_percent == 5
    assert settings.size_limit_mb == {"image": 500, "card": 500, "3D": 1024, "pdf": 200}


def test_load_all_takes_the_deployments_museums() -> None:
    loaded = museum.load_all({"ucjeps": "https://u.test", "pahma": "https://p.test"})
    assert list(loaded) == ["pahma", "ucjeps"]


def test_a_museum_without_a_file_fails() -> None:
    with pytest.raises(ValueError, match="no configuration"):
        museum.load_all({"nowhere": "https://n.test"})


def _config(**changes: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "key": "test", "name": "Test", "derivatives": ["Thumbnail"], "original": False,
        "settings": {"watchdog_deadline": "08:00", "etl_poll_interval_seconds": 15, "etl_step_timeout_seconds": 1800,
                     "change_threshold_percent": 5, "size_limit_mb": {"image": 1, "card": 1, "3D": 1, "pdf": 1}},
    }
    config.update(changes)
    return config


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"derivatives": ["Huge"]}, "unknown derivatives"),
        ({"derivatives": []}, "at least one"),
        ({"derivatives": ["Thumbnail", "Thumbnail"]}, "twice"),
        ({"restricted_image_blob_csid": "not/a/csid"}, "isn't a CSID"),
        ({"key": "PAHMA"}, "lower-case"),
        ({"surprise": 1}, "Extra inputs"),
    ],
)
def test_bad_configuration_fails(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        museum.Museum.model_validate(_config(**changes))


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"watchdog_deadline": "8am"}, "HH:MM"),
        ({"watchdog_deadline": "24:00"}, "HH:MM"),
        ({"change_threshold_percent": 0}, "greater than 0"),
        ({"size_limit_mb": {"image": 1, "card": 1, "3D": 1}}, "pdf"),
        ({"size_limit_mb": {"image": 0, "card": 1, "3D": 1, "pdf": 1}}, "positive"),
    ],
)
def test_bad_settings_fail(settings: dict[str, Any], message: str) -> None:
    config = _config()
    config["settings"] = {**config["settings"], **settings}
    with pytest.raises(ValidationError, match=message):
        museum.Museum.model_validate(config)
