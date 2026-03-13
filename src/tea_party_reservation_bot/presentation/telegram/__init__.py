from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tea_party_reservation_bot.presentation.telegram.runtime import BotRuntime

__all__ = ["BotRuntime"]


def __getattr__(name: str) -> Any:
    if name == "BotRuntime":
        return import_module("tea_party_reservation_bot.presentation.telegram.runtime").BotRuntime
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
