"""A phase's requests, sent once and checked by several tests: each step's sends are remembered with the Blob and size
they ask for, and an error while sending is kept for that step's test to raise (the others still run)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from serenade.qa.harness import Log, Sent, Serena


@dataclass
class Asked:
    sent: Sent
    blob: str | None
    size: str | None   # a derivative, or None for the original


@dataclass
class Step:
    asked: dict[str, Asked] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    error: BaseException | None = None

    def ask(self, serena: Serena, label: str, url: str, blob: str | None = None, size: str | None = None) -> Sent:
        sent = serena.send(url)
        self.asked[label] = Asked(sent, blob, size)
        return sent

    def checked(self) -> Step:
        """The step, for its test; the error its sends met, if any."""
        if self.error is not None:
            raise AssertionError(f"sending this step's requests failed: {self.error!r}") from self.error
        return self

    def __getitem__(self, label: str) -> Sent:
        return self.asked[label].sent


Sender = Callable[[Step], None]


def send_all(senders: list[tuple[int, Sender]], serena: Serena, log: Log) -> dict[int, Step]:
    """Every step's requests in order, then one wait for all their log lines."""
    steps: dict[int, Step] = {}
    for number, send in senders:
        step = Step()
        try:
            send(step)
        except Exception as error:  # kept for the step's own test; the other steps still send
            step.error = error
        steps[number] = step
    log.catch_up(serena.sent)
    return steps
