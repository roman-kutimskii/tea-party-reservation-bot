from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tea_party_reservation_bot.domain.enums import (
    CancelDeadlineSource,
    EventStatus,
    PublicationBatchStatus,
    ReservationStatus,
    WaitlistStatus,
)
from tea_party_reservation_bot.infrastructure.db.base import Base, TimestampedMixin

json_type = JSONB().with_variant(JSON(), "sqlite")


class UserModel(TimestampedMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)


class RoleModel(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class RoleAssignmentModel(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC), nullable=False
    )


class PublicationBatchModel(TimestampedMixin, Base):
    __tablename__ = "publication_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_label: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    telegram_group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_group_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventOccurrenceModel(TimestampedMixin, Base):
    __tablename__ = "event_occurrences"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint("reserved_seats >= 0", name="reserved_seats_non_negative"),
        CheckConstraint("reserved_seats <= capacity", name="reserved_seats_not_over_capacity"),
        CheckConstraint("cancel_deadline_at <= starts_at", name="cancel_deadline_before_start"),
        Index("ix_event_occurrences_status_starts_at", "status", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tea_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_seats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_deadline_source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    publication_batch_id: Mapped[int | None] = mapped_column(ForeignKey("publication_batches.id"))
    telegram_group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_group_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def sync_status_from_capacity(self) -> None:
        if self.status in {EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.DRAFT}:
            return
        if self.status == EventStatus.REGISTRATION_CLOSED:
            return
        self.status = (
            EventStatus.PUBLISHED_FULL
            if self.reserved_seats >= self.capacity
            else EventStatus.PUBLISHED_OPEN
        )


class PublicationBatchEventModel(Base):
    __tablename__ = "publication_batch_events"
    __table_args__ = (UniqueConstraint("batch_id", "event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("publication_batches.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("event_occurrences.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ReservationModel(TimestampedMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_event_id_status", "event_id", "status"),
        Index(
            "uq_reservations_event_id_user_id_active",
            "event_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("event_occurrences.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    promoted_from_waitlist_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("waitlist_entries.id")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WaitlistEntryModel(TimestampedMixin, Base):
    __tablename__ = "waitlist_entries"
    __table_args__ = (
        Index("ix_waitlist_entries_event_id_status_position", "event_id", "status", "position"),
        Index(
            "uq_waitlist_entries_event_id_user_id_active",
            "event_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("event_occurrences.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreferenceModel(TimestampedMixin, Base):
    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    new_events_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SystemSettingsModel(TimestampedMixin, Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    default_cancel_deadline_offset_minutes: Mapped[int] = mapped_column(
        Integer,
        default=240,
        nullable=False,
    )


class ProcessedCommandModel(Base):
    __tablename__ = "processed_commands"
    __table_args__ = (UniqueConstraint("source", "idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC), nullable=False
    )


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_sent_at_available_at", "sent_at", "available_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC), nullable=False
    )


class AdminAuditLogModel(Base):
    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC), nullable=False
    )


__all__ = [
    "AdminAuditLogModel",
    "CancelDeadlineSource",
    "EventOccurrenceModel",
    "EventStatus",
    "NotificationPreferenceModel",
    "OutboxEventModel",
    "ProcessedCommandModel",
    "PublicationBatchEventModel",
    "PublicationBatchModel",
    "PublicationBatchStatus",
    "ReservationModel",
    "ReservationStatus",
    "RoleAssignmentModel",
    "RoleModel",
    "SystemSettingsModel",
    "UserModel",
    "WaitlistEntryModel",
    "WaitlistStatus",
]
