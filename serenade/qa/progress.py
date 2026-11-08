"""Progress lines for the synthetic-record runs, shown as they happen: pytest holds a test's output until it ends, and
some parts take minutes (make-test-media.py, the log waits, the settings waits), so without these a run looks hung.
Each line has the time, so a pause shows how long it's been."""
from __future__ import annotations

import time

import pytest

_config: pytest.Config | None = None


def setup(config: pytest.Config) -> None:
    global _config
    _config = config


def say(text: str) -> None:
    """Writes one line to the terminal now, past pytest's capture."""
    line = f"  [{time.strftime('%H:%M:%S')}] {text}"
    capture = _config.pluginmanager.getplugin("capturemanager") if _config else None
    if capture is None:
        print(line, flush=True)
        return
    with capture.global_and_fixture_disabled():
        print(line, flush=True)


def wait(seconds: int, why: str) -> None:
    """Sleeps, saying so every 15 seconds."""
    say(f"waiting {seconds} s: {why}")
    left = seconds
    while left > 0:
        step = min(15, left)
        time.sleep(step)
        left -= step
        if left:
            say(f"  {left} s left")
