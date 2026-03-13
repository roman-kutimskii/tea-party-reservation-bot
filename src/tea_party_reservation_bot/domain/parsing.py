from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfoNotFoundError

from tea_party_reservation_bot.domain.enums import CancelDeadlineSource
from tea_party_reservation_bot.domain.events import EventDraft, EventInputBlock, EventPreview
from tea_party_reservation_bot.exceptions import ValidationError
from tea_party_reservation_bot.time import ensure_timezone, load_timezone, now_utc

DATE_FORMAT: Final[str] = "%d.%m.%Y"
TIME_FORMAT: Final[str] = "%H:%M"
DATETIME_FORMAT: Final[str] = "%d.%m.%Y %H:%M"
BLOCK_SEPARATOR: Final[str] = "---"


@dataclass(slots=True, frozen=True)
class FieldError:
    field_name: str
    message: str
    block_number: int | None = None

    def to_user_string(self) -> str:
        prefix = f"Блок {self.block_number}: " if self.block_number is not None else ""
        return f'{prefix}Поле "{self.field_name}": {self.message}'


class AdminEventInputParser:
    REQUIRED_FIELDS: Final[frozenset[str]] = frozenset({"Чай", "Дата", "Время", "Мест"})
    OPTIONAL_FIELDS: Final[frozenset[str]] = frozenset({"Отмена до", "Описание"})

    def __init__(self, default_cancel_deadline_offset_minutes: int) -> None:
        self._default_cancel_deadline_offset_minutes = default_cancel_deadline_offset_minutes

    def parse_many(self, raw_text: str, timezone_name: str) -> list[EventPreview]:
        blocks = [block.strip() for block in raw_text.split(BLOCK_SEPARATOR) if block.strip()]
        if not blocks:
            raise BatchValidationError(
                [FieldError(field_name="Формат", message="нужен хотя бы один блок события")]
            )
        previews: list[EventPreview] = []
        errors: list[FieldError] = []

        for index, raw_block in enumerate(blocks, start=1):
            try:
                draft = self.parse_one(raw_block, timezone_name=timezone_name)
            except BatchValidationError as exc:
                errors.extend(
                    FieldError(
                        field_name=error.field_name,
                        message=error.message,
                        block_number=index,
                    )
                    for error in exc.errors
                )
                continue
            previews.append(EventPreview(normalized=draft, block_number=index))

        if errors:
            raise BatchValidationError(errors)
        return previews

    def parse_one(self, raw_text: str, timezone_name: str) -> EventDraft:
        timezone = self._load_timezone(timezone_name)
        field_map = self._parse_fields(raw_text)
        errors = self._validate_fields(field_map, timezone)
        if errors:
            raise BatchValidationError(errors)
        block = self._build_input_block(field_map, timezone)
        return EventDraft.from_input_block(block)

    def _parse_fields(self, raw_text: str) -> dict[str, str]:
        field_map: dict[str, str] = {}
        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                raise BatchValidationError(
                    [FieldError(field_name="Формат", message="нужен вид Ключ: значение")]
                )
            key, value = line.split(":", maxsplit=1)
            normalized_key = key.strip()
            normalized_value = value.strip()
            if normalized_key in field_map:
                raise BatchValidationError(
                    [FieldError(field_name=normalized_key, message="поле указано повторно")]
                )
            field_map[normalized_key] = normalized_value
        return field_map

    def _validate_fields(self, field_map: dict[str, str], timezone: tzinfo) -> list[FieldError]:
        errors: list[FieldError] = []
        allowed_fields = self.REQUIRED_FIELDS | self.OPTIONAL_FIELDS

        for field_name in self.REQUIRED_FIELDS:
            if not field_map.get(field_name):
                errors.append(FieldError(field_name=field_name, message="поле обязательно"))

        for field_name in field_map:
            if field_name not in allowed_fields:
                errors.append(FieldError(field_name=field_name, message="поле не поддерживается"))

        if date_value := field_map.get("Дата"):
            if self._parse_date(date_value) is None:
                errors.append(FieldError(field_name="Дата", message="нужен формат ДД.ММ.ГГГГ"))
        if time_value := field_map.get("Время"):
            if self._parse_time(time_value) is None:
                errors.append(FieldError(field_name="Время", message="нужен формат ЧЧ:ММ"))
        if capacity_value := field_map.get("Мест"):
            if not capacity_value.isdigit() or int(capacity_value) <= 0:
                errors.append(FieldError(field_name="Мест", message="только целое число больше 0"))
        if cancel_value := field_map.get("Отмена до"):
            if self._parse_datetime(cancel_value) is None:
                errors.append(
                    FieldError(field_name="Отмена до", message="нужен формат ДД.ММ.ГГГГ ЧЧ:ММ")
                )

        if errors:
            return errors

        starts_at_local = self._combine_start(field_map, timezone)
        if starts_at_local <= now_utc().astimezone(starts_at_local.tzinfo):
            errors.append(FieldError(field_name="Дата", message="событие должно быть в будущем"))
        if cancel_value := field_map.get("Отмена до"):
            parsed_cancel_deadline = self._parse_datetime(cancel_value)
            assert parsed_cancel_deadline is not None
            cancel_deadline_at_local = ensure_timezone(parsed_cancel_deadline, timezone)
            if cancel_deadline_at_local >= starts_at_local:
                errors.append(
                    FieldError(
                        field_name="Отмена до",
                        message="должно быть раньше начала события",
                    )
                )
        return errors

    def _build_input_block(self, field_map: dict[str, str], timezone: tzinfo) -> EventInputBlock:
        starts_at_local = self._combine_start(field_map, timezone)
        cancel_raw = field_map.get("Отмена до")
        if cancel_raw is None:
            cancel_deadline_at_local = starts_at_local - self._default_deadline_delta
            source = CancelDeadlineSource.DEFAULT
        else:
            parsed_cancel_deadline = self._parse_datetime(cancel_raw)
            assert parsed_cancel_deadline is not None
            cancel_deadline_at_local = ensure_timezone(parsed_cancel_deadline, timezone)
            source = CancelDeadlineSource.OVERRIDE

        description = field_map.get("Описание") or None
        return EventInputBlock(
            tea_name=field_map["Чай"],
            starts_at_local=starts_at_local,
            capacity=int(field_map["Мест"]),
            cancel_deadline_at_local=cancel_deadline_at_local,
            cancel_deadline_source=source,
            description=description,
        )

    @property
    def _default_deadline_delta(self) -> timedelta:
        return timedelta(minutes=self._default_cancel_deadline_offset_minutes)

    def _combine_start(self, field_map: dict[str, str], timezone: tzinfo) -> datetime:
        date_part = self._parse_date(field_map["Дата"])
        time_part = self._parse_time(field_map["Время"])
        if date_part is None or time_part is None:
            msg = "Дата и время должны быть валидны до сборки события."
            raise BatchValidationError([FieldError(field_name="Формат", message=msg)])
        combined = datetime.combine(date_part, time_part)
        return ensure_timezone(combined, timezone)

    def _load_timezone(self, timezone_name: str) -> tzinfo:
        try:
            return load_timezone(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError("Неизвестный часовой пояс.") from exc

    @staticmethod
    def _parse_date(value: str) -> date | None:
        try:
            return datetime.strptime(value, DATE_FORMAT).date()
        except ValueError:
            return None

    @staticmethod
    def _parse_time(value: str) -> time | None:
        try:
            return datetime.strptime(value, TIME_FORMAT).time()
        except ValueError:
            return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        try:
            return datetime.strptime(value, DATETIME_FORMAT)
        except ValueError:
            return None


class BatchValidationError(ValidationError):
    def __init__(self, errors: list[FieldError]) -> None:
        self.errors = errors
        super().__init__("\n".join(error.to_user_string() for error in errors))
