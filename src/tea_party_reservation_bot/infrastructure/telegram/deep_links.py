from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass

EVENT_PREFIX = "event-"


@dataclass(slots=True, frozen=True)
class TelegramStartContext:
    event_id: str | None = None

    @property
    def has_event(self) -> bool:
        return self.event_id is not None


def encode_event_start_parameter(event_id: str) -> str:
    encoded = urlsafe_b64encode(event_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{EVENT_PREFIX}{encoded}"


def decode_start_parameter(value: str | None) -> TelegramStartContext:
    if value is None or not value.startswith(EVENT_PREFIX):
        return TelegramStartContext()
    encoded = value.removeprefix(EVENT_PREFIX)
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = urlsafe_b64decode(f"{encoded}{padding}").decode("utf-8")
    except ValueError, UnicodeDecodeError:
        return TelegramStartContext()
    return TelegramStartContext(event_id=decoded)


def build_event_deep_link(*, bot_username: str, event_id: str) -> str:
    payload = encode_event_start_parameter(event_id)
    username = bot_username.removeprefix("@")
    return f"https://t.me/{username}?start={payload}"
