"""A museum's settings now: its YAML starting values with an admin's values over them (design: Records, Settings).

Each task keeps them for settings_cache_seconds, so an admin's change takes effect within about a minute. An admin's
value that isn't valid is ignored (logged), and the starting value used."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from pydantic import ValidationError

from .museum import Museum, StartingSettings
from .store import Store

log = logging.getLogger("serena.settings")


class MuseumSettings:
    def __init__(self, store: Store, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.ttl = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, StartingSettings]] = {}

    def get(self, museum: Museum) -> StartingSettings:
        now = self.clock()
        with self._lock:
            cached = self._cache.get(museum.key)
            if cached and now - cached[0] < self.ttl:
                return cached[1]
        current = self._read(museum)
        with self._lock:
            self._cache[museum.key] = (now, current)
        return current

    def _read(self, museum: Museum) -> StartingSettings:
        overrides = self.store.settings_overrides(museum.key)
        if not overrides:
            return museum.settings
        try:
            return StartingSettings.model_validate({**museum.settings.model_dump(), **overrides})
        except ValidationError as error:
            log.warning("an admin's settings for this museum aren't valid; using the starting values",
                        extra={"museum": museum.key, "errors": error.error_count()})
            return museum.settings
