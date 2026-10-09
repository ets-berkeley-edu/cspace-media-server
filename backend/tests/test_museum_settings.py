import json

from serena import museum, tables
from serena.museum_settings import MuseumSettings
from serena.store import Store


def _override(store: Store, tenant: str, values: object) -> None:
    store.client.put_item(TableName=store.table(tables.SETTINGS),
                          Item={"pk": {"S": tenant}, "values": {"S": json.dumps(values)}})


def test_starting_values_without_an_admins(store: Store) -> None:
    pahma = museum.load("pahma")
    assert MuseumSettings(store, 60).get(pahma) == pahma.settings


def test_an_admins_value_overrides_the_starting_value(store: Store) -> None:
    pahma = museum.load("pahma")
    _override(store, "pahma", {"watchdog_deadline": "07:30", "size_limit_mb": {"image": 50, "card": 50, "3D": 50,
                                                                               "pdf": 50}})
    current = MuseumSettings(store, 60).get(pahma)
    assert current.watchdog_deadline == "07:30"
    assert current.size_limit_mb["image"] == 50
    assert current.etl_step_timeout_seconds == pahma.settings.etl_step_timeout_seconds  # the others unchanged


def test_kept_for_a_while_then_read_again(store: Store) -> None:
    pahma = museum.load("pahma")
    now = [0.0]
    settings = MuseumSettings(store, 60, clock=lambda: now[0])
    assert settings.get(pahma).watchdog_deadline == "08:00"
    _override(store, "pahma", {"watchdog_deadline": "06:00"})
    now[0] = 59
    assert settings.get(pahma).watchdog_deadline == "08:00"
    now[0] = 61
    assert settings.get(pahma).watchdog_deadline == "06:00"


def test_an_invalid_value_is_ignored(store: Store) -> None:
    pahma = museum.load("pahma")
    _override(store, "pahma", {"watchdog_deadline": "late"})
    assert MuseumSettings(store, 60).get(pahma) == pahma.settings
