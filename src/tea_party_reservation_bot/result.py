from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Result[T, E]:
    value: T | None = None
    error: E | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def unwrap(self) -> T:
        if self.error is not None:
            msg = f"result has error: {self.error!r}"
            raise ValueError(msg)
        assert self.value is not None
        return self.value
