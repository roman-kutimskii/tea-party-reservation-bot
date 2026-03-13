from tea_party_reservation_bot.infrastructure.telegram.deep_links import (
    build_event_deep_link,
    decode_start_parameter,
    encode_event_start_parameter,
)


def test_event_start_parameter_round_trip() -> None:
    payload = encode_event_start_parameter("event-42")

    result = decode_start_parameter(payload)

    assert result.event_id == "event-42"


def test_build_event_deep_link_uses_start_payload() -> None:
    link = build_event_deep_link(bot_username="tea_party_bot", event_id="abc")

    assert link.startswith("https://t.me/tea_party_bot?start=event-")
