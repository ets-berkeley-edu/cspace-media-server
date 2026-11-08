"""A password that never shows itself in a traceback: pytest prints the arguments of every function in a failing
test's traceback (a fixture's value, a page method's `password`) with repr(), and a plain str would put the password in
the terminal and in whatever the output is pasted into. Secret masks only repr(): it's still the str Selenium types (its
send_keys calls str() on what it's given). Never format one into a message."""
from __future__ import annotations


class Secret(str):
    __slots__ = ()

    def __repr__(self) -> str:
        return "'********'"
