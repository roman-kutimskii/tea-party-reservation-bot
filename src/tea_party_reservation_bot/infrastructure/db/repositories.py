from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tea_party_reservation_bot.application.dto import (
    ActiveRegistrationView,
    AdminRoleAssignmentView,
    NotificationPreferenceView,
    OutboxMessage,
    ProcessedCommandResult,
    PublicationIntent,
    RosterEntryView,
    StoredEvent,
    StoredUser,
    SystemSettingsView,
    TelegramProfile,
)
from tea_party_reservation_bot.domain.enums import (
    AdminRole,
    EventStatus,
    PublicationBatchStatus,
    ReservationStatus,
    WaitlistStatus,
)
from tea_party_reservation_bot.domain.events import EventDraft
from tea_party_reservation_bot.domain.rbac import Actor, RoleSet
from tea_party_reservation_bot.infrastructure.db.models import (
    AdminAuditLogModel,
    EventOccurrenceModel,
    NotificationPreferenceModel,
    OutboxEventModel,
    ProcessedCommandModel,
    PublicationBatchEventModel,
    PublicationBatchModel,
    ReservationModel,
    RoleAssignmentModel,
    RoleModel,
    SystemSettingsModel,
    UserModel,
    WaitlistEntryModel,
)


@dataclass(slots=True)
class UserRepository:
    session: AsyncSession

    async def ensure_from_telegram_profile(self, profile: TelegramProfile) -> StoredUser:
        result = await self.session.execute(
            select(UserModel).where(UserModel.telegram_user_id == profile.telegram_user_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = UserModel(
                telegram_user_id=profile.telegram_user_id,
                username=profile.username,
                first_name=profile.first_name,
                last_name=profile.last_name,
            )
            self.session.add(model)
            await self.session.flush()
        else:
            model.username = profile.username
            model.first_name = profile.first_name
            model.last_name = profile.last_name
            await self.session.flush()
        return StoredUser(
            id=model.id,
            telegram_user_id=model.telegram_user_id,
            username=model.username,
            first_name=model.first_name,
            last_name=model.last_name,
        )

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> StoredUser | None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.telegram_user_id == telegram_user_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return StoredUser(
            id=model.id,
            telegram_user_id=model.telegram_user_id,
            username=model.username,
            first_name=model.first_name,
            last_name=model.last_name,
        )

    async def get_by_id(self, user_id: int) -> StoredUser | None:
        model = await self.session.get(UserModel, user_id)
        if model is None:
            return None
        return StoredUser(
            id=model.id,
            telegram_user_id=model.telegram_user_id,
            username=model.username,
            first_name=model.first_name,
            last_name=model.last_name,
        )


def _published_event_status(model: EventOccurrenceModel) -> EventStatus:
    if model.reserved_seats >= model.capacity:
        return EventStatus.PUBLISHED_FULL
    return EventStatus.PUBLISHED_OPEN


@dataclass(slots=True)
class RoleRepository:
    session: AsyncSession

    async def get_roles_for_telegram_user(self, telegram_user_id: int) -> frozenset[AdminRole]:
        stmt = (
            select(RoleModel.code)
            .join(RoleAssignmentModel, RoleAssignmentModel.role_id == RoleModel.id)
            .join(UserModel, UserModel.id == RoleAssignmentModel.user_id)
            .where(UserModel.telegram_user_id == telegram_user_id)
        )
        result = await self.session.execute(stmt)
        return frozenset(AdminRole(code) for code in result.scalars().all())

    async def get_actor(self, telegram_user_id: int) -> Actor:
        return Actor(
            telegram_user_id=telegram_user_id,
            roles=RoleSet(await self.get_roles_for_telegram_user(telegram_user_id)),
        )

    async def list_admin_role_assignments(self) -> list[AdminRoleAssignmentView]:
        stmt = (
            select(UserModel, RoleModel.code)
            .join(RoleAssignmentModel, RoleAssignmentModel.user_id == UserModel.id)
            .join(RoleModel, RoleModel.id == RoleAssignmentModel.role_id)
            .order_by(UserModel.telegram_user_id.asc(), RoleModel.code.asc())
        )
        result = await self.session.execute(stmt)
        assignments: dict[int, AdminRoleAssignmentView] = {}
        for user, role_code in result.all():
            current = assignments.get(user.id)
            role = AdminRole(role_code)
            if current is None:
                assignments[user.id] = AdminRoleAssignmentView(
                    telegram_user_id=user.telegram_user_id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    roles=frozenset({role}),
                )
                continue
            assignments[user.id] = AdminRoleAssignmentView(
                telegram_user_id=current.telegram_user_id,
                username=current.username,
                first_name=current.first_name,
                last_name=current.last_name,
                roles=frozenset({*current.roles, role}),
            )
        return list(assignments.values())

    async def assign_role(self, *, user_id: int, role: AdminRole) -> bool:
        role_id = await self.session.scalar(
            select(RoleModel.id).where(RoleModel.code == role.value)
        )
        if role_id is None:
            msg = f"Role {role.value} not found"
            raise LookupError(msg)
        existing = await self.session.scalar(
            select(RoleAssignmentModel.id).where(
                RoleAssignmentModel.user_id == user_id,
                RoleAssignmentModel.role_id == role_id,
            )
        )
        if existing is not None:
            return False
        self.session.add(RoleAssignmentModel(user_id=user_id, role_id=role_id))
        await self.session.flush()
        return True

    async def revoke_role(self, *, user_id: int, role: AdminRole) -> bool:
        role_id = await self.session.scalar(
            select(RoleModel.id).where(RoleModel.code == role.value)
        )
        if role_id is None:
            msg = f"Role {role.value} not found"
            raise LookupError(msg)
        assignment = await self.session.scalar(
            select(RoleAssignmentModel).where(
                RoleAssignmentModel.user_id == user_id,
                RoleAssignmentModel.role_id == role_id,
            )
        )
        if assignment is None:
            return False
        await self.session.delete(assignment)
        await self.session.flush()
        return True

    async def count_users_with_role(self, role: AdminRole) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(RoleAssignmentModel)
                .join(RoleModel, RoleModel.id == RoleAssignmentModel.role_id)
                .where(RoleModel.code == role.value)
            )
            or 0
        )


@dataclass(slots=True)
class SystemSettingsRepository:
    session: AsyncSession

    async def get(self) -> SystemSettingsView:
        model = await self._get_or_create_model()
        return SystemSettingsView(
            default_cancel_deadline_offset_minutes=model.default_cancel_deadline_offset_minutes
        )

    async def set_default_cancel_deadline_offset_minutes(self, minutes: int) -> SystemSettingsView:
        model = await self._get_or_create_model()
        model.default_cancel_deadline_offset_minutes = minutes
        await self.session.flush()
        return SystemSettingsView(default_cancel_deadline_offset_minutes=minutes)

    async def _get_or_create_model(self) -> SystemSettingsModel:
        model = await self.session.get(SystemSettingsModel, 1)
        if model is None:
            model = SystemSettingsModel(id=1, default_cancel_deadline_offset_minutes=240)
            self.session.add(model)
            await self.session.flush()
        return model


@dataclass(slots=True)
class EventRepository:
    session: AsyncSession

    async def save_drafts(
        self, drafts: Sequence[EventDraft], *, actor_user_id: int, timezone_name: str
    ) -> list[int]:
        created_ids: list[int] = []
        for draft in drafts:
            model = EventOccurrenceModel(
                tea_name=draft.tea_name,
                description=draft.description,
                starts_at=draft.starts_at_utc,
                timezone=timezone_name,
                capacity=draft.capacity,
                reserved_seats=0,
                cancel_deadline_at=draft.cancel_deadline_at_utc,
                cancel_deadline_source=draft.cancel_deadline_source,
                status=draft.status,
                created_by_user_id=actor_user_id,
            )
            self.session.add(model)
            await self.session.flush()
            created_ids.append(model.id)
        return created_ids

    async def get_by_id(
        self, event_id: int, *, for_update: bool = False
    ) -> EventOccurrenceModel | None:
        stmt: Select[tuple[EventOccurrenceModel]] = select(EventOccurrenceModel).where(
            EventOccurrenceModel.id == event_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_published_upcoming(self, now: datetime) -> list[StoredEvent]:
        stmt = (
            select(EventOccurrenceModel)
            .where(
                EventOccurrenceModel.status.in_(
                    [
                        EventStatus.PUBLISHED_OPEN,
                        EventStatus.PUBLISHED_FULL,
                    ]
                ),
                EventOccurrenceModel.starts_at > now,
            )
            .order_by(EventOccurrenceModel.starts_at.asc(), EventOccurrenceModel.id.asc())
        )
        result = await self.session.execute(stmt)
        return [self._to_stored_event(model) for model in result.scalars().all()]

    async def list_publication_event_ids(self, batch_id: int) -> tuple[int, ...]:
        result = await self.session.execute(
            select(EventOccurrenceModel.id)
            .join(
                PublicationBatchEventModel,
                PublicationBatchEventModel.event_id == EventOccurrenceModel.id,
                isouter=True,
            )
            .where(EventOccurrenceModel.publication_batch_id == batch_id)
            .order_by(PublicationBatchEventModel.sort_order.asc(), EventOccurrenceModel.id.asc())
        )
        return tuple(result.scalars().all())

    async def mark_publication_succeeded(
        self,
        *,
        event_ids: Sequence[int],
        chat_id: int,
        message_id: int,
        published_at: datetime,
    ) -> None:
        for event_id in event_ids:
            model = await self.get_by_id(event_id, for_update=True)
            if model is None:
                continue
            model.status = _published_event_status(model)
            model.telegram_group_chat_id = chat_id
            model.telegram_group_message_id = message_id
            model.published_at = published_at
        await self.session.flush()

    async def mark_publication_failed(self, *, event_ids: Sequence[int]) -> None:
        for event_id in event_ids:
            model = await self.get_by_id(event_id, for_update=True)
            if model is None:
                continue
            model.status = EventStatus.DRAFT
            model.publication_batch_id = None
            model.telegram_group_chat_id = None
            model.telegram_group_message_id = None
            model.published_at = None
        await self.session.flush()

    async def list_active_registrations_for_user(
        self, user_id: int
    ) -> list[ActiveRegistrationView]:
        reservations_stmt = (
            select(ReservationModel, EventOccurrenceModel)
            .join(EventOccurrenceModel, EventOccurrenceModel.id == ReservationModel.event_id)
            .where(
                ReservationModel.user_id == user_id,
                ReservationModel.status == ReservationStatus.CONFIRMED,
            )
            .order_by(EventOccurrenceModel.starts_at.asc())
        )
        waitlist_stmt = (
            select(WaitlistEntryModel, EventOccurrenceModel)
            .join(EventOccurrenceModel, EventOccurrenceModel.id == WaitlistEntryModel.event_id)
            .where(
                WaitlistEntryModel.user_id == user_id,
                WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
            )
            .order_by(EventOccurrenceModel.starts_at.asc(), WaitlistEntryModel.position.asc())
        )
        reservations = await self.session.execute(reservations_stmt)
        waitlist = await self.session.execute(waitlist_stmt)
        rows = [
            ActiveRegistrationView(
                reservation_id=reservation.id,
                event_id=event.id,
                tea_name=event.tea_name,
                starts_at=event.starts_at,
                cancel_deadline_at=event.cancel_deadline_at,
                status=reservation.status,
            )
            for reservation, event in reservations.all()
        ]
        rows.extend(
            ActiveRegistrationView(
                reservation_id=0,
                event_id=event.id,
                tea_name=event.tea_name,
                starts_at=event.starts_at,
                cancel_deadline_at=event.cancel_deadline_at,
                status=entry.status,
                waitlist_position=entry.position,
            )
            for entry, event in waitlist.all()
        )
        return sorted(
            rows, key=lambda item: (item.starts_at, item.event_id, item.waitlist_position or 0)
        )

    async def get_roster(self, event_id: int) -> list[RosterEntryView]:
        confirmed_stmt = (
            select(ReservationModel, UserModel)
            .join(UserModel, UserModel.id == ReservationModel.user_id)
            .where(
                ReservationModel.event_id == event_id,
                ReservationModel.status == ReservationStatus.CONFIRMED,
            )
            .order_by(ReservationModel.created_at.asc(), ReservationModel.id.asc())
        )
        waitlist_stmt = (
            select(WaitlistEntryModel, UserModel)
            .join(UserModel, UserModel.id == WaitlistEntryModel.user_id)
            .where(
                WaitlistEntryModel.event_id == event_id,
                WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
            )
            .order_by(WaitlistEntryModel.position.asc(), WaitlistEntryModel.id.asc())
        )
        confirmed = await self.session.execute(confirmed_stmt)
        waitlist = await self.session.execute(waitlist_stmt)
        rows: list[RosterEntryView] = []
        rows.extend(
            RosterEntryView(
                user_id=user.id,
                telegram_user_id=user.telegram_user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                kind="reservation",
                status=reservation.status,
                position=None,
                reservation_id=reservation.id,
                waitlist_entry_id=None,
            )
            for reservation, user in confirmed.all()
        )
        rows.extend(
            RosterEntryView(
                user_id=user.id,
                telegram_user_id=user.telegram_user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                kind="waitlist",
                status=entry.status,
                position=entry.position,
                reservation_id=None,
                waitlist_entry_id=entry.id,
            )
            for entry, user in waitlist.all()
        )
        return rows

    async def list_active_participant_telegram_user_ids(self, event_id: int) -> list[int]:
        confirmed_stmt = (
            select(UserModel.telegram_user_id)
            .join(ReservationModel, ReservationModel.user_id == UserModel.id)
            .where(
                ReservationModel.event_id == event_id,
                ReservationModel.status == ReservationStatus.CONFIRMED,
            )
        )
        waitlist_stmt = (
            select(UserModel.telegram_user_id)
            .join(WaitlistEntryModel, WaitlistEntryModel.user_id == UserModel.id)
            .where(
                WaitlistEntryModel.event_id == event_id,
                WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
            )
        )
        confirmed_ids = list((await self.session.execute(confirmed_stmt)).scalars().all())
        waitlist_ids = list((await self.session.execute(waitlist_stmt)).scalars().all())
        return list(dict.fromkeys([*confirmed_ids, *waitlist_ids]))

    def _to_stored_event(self, model: EventOccurrenceModel) -> StoredEvent:
        return StoredEvent(
            id=model.id,
            tea_name=model.tea_name,
            description=model.description,
            starts_at=model.starts_at,
            timezone=model.timezone,
            capacity=model.capacity,
            reserved_seats=model.reserved_seats,
            cancel_deadline_at=model.cancel_deadline_at,
            cancel_deadline_source=model.cancel_deadline_source,
            status=model.status,
            publication_batch_id=model.publication_batch_id,
            published_at=model.published_at,
            telegram_group_chat_id=model.telegram_group_chat_id,
            telegram_group_message_id=model.telegram_group_message_id,
        )


@dataclass(slots=True)
class NotificationPreferenceRepository:
    session: AsyncSession

    async def get_or_create(self, user_id: int) -> NotificationPreferenceView:
        result = await self.session.execute(
            select(NotificationPreferenceModel).where(
                NotificationPreferenceModel.user_id == user_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = NotificationPreferenceModel(user_id=user_id, new_events_enabled=False)
            self.session.add(model)
            await self.session.flush()
        return NotificationPreferenceView(
            user_id=model.user_id, new_events_enabled=model.new_events_enabled
        )

    async def set_enabled(self, user_id: int, enabled: bool) -> NotificationPreferenceView:
        result = await self.session.execute(
            select(NotificationPreferenceModel).where(
                NotificationPreferenceModel.user_id == user_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = NotificationPreferenceModel(user_id=user_id, new_events_enabled=enabled)
            self.session.add(model)
        else:
            model.new_events_enabled = enabled
        await self.session.flush()
        return NotificationPreferenceView(
            user_id=user_id, new_events_enabled=model.new_events_enabled
        )

    async def list_enabled_telegram_user_ids(self) -> list[int]:
        result = await self.session.execute(
            select(UserModel.telegram_user_id)
            .join(NotificationPreferenceModel, NotificationPreferenceModel.user_id == UserModel.id)
            .where(NotificationPreferenceModel.new_events_enabled.is_(True))
            .order_by(UserModel.telegram_user_id.asc())
        )
        return list(result.scalars().all())


@dataclass(slots=True)
class OutboxRepository:
    session: AsyncSession

    async def enqueue(self, message: OutboxMessage) -> None:
        self.session.add(
            OutboxEventModel(
                aggregate_type=message.aggregate_type,
                aggregate_id=message.aggregate_id,
                event_type=message.event_type,
                payload_json=message.payload,
                available_at=message.available_at,
            )
        )
        await self.session.flush()

    async def fetch_pending(self, now: datetime, *, limit: int = 100) -> list[OutboxMessage]:
        result = await self.session.execute(
            select(OutboxEventModel)
            .where(OutboxEventModel.sent_at.is_(None), OutboxEventModel.available_at <= now)
            .order_by(OutboxEventModel.created_at.asc(), OutboxEventModel.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = result.scalars().all()
        return [
            OutboxMessage(
                id=row.id,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                event_type=row.event_type,
                payload=row.payload_json,
                available_at=row.available_at,
                attempt_count=row.attempt_count,
                last_error=row.last_error,
            )
            for row in rows
        ]

    async def mark_sent(self, *, event_id: int, sent_at: datetime) -> None:
        row = await self.session.get(OutboxEventModel, event_id, with_for_update=True)
        if row is None:
            return
        row.sent_at = sent_at
        row.last_error = None
        await self.session.flush()

    async def mark_failed(
        self,
        *,
        event_id: int,
        available_at: datetime,
        last_error: str,
        payload_updates: dict[str, Any] | None = None,
    ) -> None:
        row = await self.session.get(OutboxEventModel, event_id, with_for_update=True)
        if row is None:
            return
        row.attempt_count += 1
        row.available_at = available_at
        row.last_error = last_error
        if payload_updates:
            row.payload_json = {**row.payload_json, **payload_updates}
        await self.session.flush()


@dataclass(slots=True)
class AuditLogRepository:
    session: AsyncSession

    async def append(
        self,
        *,
        actor_user_id: int,
        action: str,
        target_type: str,
        target_id: str,
        payload_json: dict[str, Any],
    ) -> None:
        self.session.add(
            AdminAuditLogModel(
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                payload_json=payload_json,
            )
        )
        await self.session.flush()


@dataclass(slots=True)
class IdempotencyRepository:
    session: AsyncSession

    async def get(self, *, source: str, idempotency_key: str) -> ProcessedCommandResult | None:
        result = await self.session.execute(
            select(ProcessedCommandModel).where(
                ProcessedCommandModel.source == source,
                ProcessedCommandModel.idempotency_key == idempotency_key,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return ProcessedCommandResult(
            source=model.source,
            idempotency_key=model.idempotency_key,
            result_ref=model.result_ref,
        )

    async def record(self, *, source: str, idempotency_key: str, result_ref: str | None) -> None:
        self.session.add(
            ProcessedCommandModel(
                source=source,
                idempotency_key=idempotency_key,
                result_ref=result_ref,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError:
            raise

    @staticmethod
    def dump_result(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def load_result(payload: str | None) -> dict[str, Any] | None:
        if payload is None:
            return None
        return cast("dict[str, Any]", json.loads(payload))


@dataclass(slots=True)
class PublicationRepository:
    session: AsyncSession

    async def create_single_event_publication_intent(
        self, *, event_id: int, actor_user_id: int
    ) -> PublicationIntent:
        event = await self.session.get(EventOccurrenceModel, event_id, with_for_update=True)
        if event is None:
            msg = f"Event {event_id} not found"
            raise LookupError(msg)
        batch = PublicationBatchModel(
            status=PublicationBatchStatus.PUBLISHING, created_by_user_id=actor_user_id
        )
        self.session.add(batch)
        await self.session.flush()
        event.publication_batch_id = batch.id
        return PublicationIntent(batch_id=batch.id, event_ids=(event.id,))

    async def create_batch_publication_intent(
        self,
        *,
        event_ids: Sequence[int],
        actor_user_id: int,
        period_label: str | None,
    ) -> PublicationIntent:
        batch = PublicationBatchModel(
            period_label=period_label,
            status=PublicationBatchStatus.PUBLISHING,
            created_by_user_id=actor_user_id,
        )
        self.session.add(batch)
        await self.session.flush()
        for sort_order, event_id in enumerate(event_ids, start=1):
            event = await self.session.get(EventOccurrenceModel, event_id, with_for_update=True)
            if event is None:
                msg = f"Event {event_id} not found"
                raise LookupError(msg)
            event.publication_batch_id = batch.id
            self.session.add(
                PublicationBatchEventModel(
                    batch_id=batch.id, event_id=event.id, sort_order=sort_order
                )
            )
        await self.session.flush()
        return PublicationIntent(batch_id=batch.id, event_ids=tuple(event_ids))

    async def mark_batch_state(
        self,
        *,
        batch_id: int,
        status: PublicationBatchStatus,
        published_at: datetime | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> None:
        batch = await self.session.get(PublicationBatchModel, batch_id, with_for_update=True)
        if batch is None:
            msg = f"Batch {batch_id} not found"
            raise LookupError(msg)
        batch.status = status
        batch.published_at = published_at
        batch.telegram_group_chat_id = chat_id
        batch.telegram_group_message_id = message_id
        await self.session.flush()


@dataclass(slots=True)
class RegistrationRepository:
    session: AsyncSession

    async def get_active_reservation(
        self, *, event_id: int, user_id: int
    ) -> ReservationModel | None:
        result = await self.session.execute(
            select(ReservationModel)
            .where(
                ReservationModel.event_id == event_id,
                ReservationModel.user_id == user_id,
                ReservationModel.status == ReservationStatus.CONFIRMED,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_active_waitlist_entry(
        self, *, event_id: int, user_id: int
    ) -> WaitlistEntryModel | None:
        result = await self.session.execute(
            select(WaitlistEntryModel)
            .where(
                WaitlistEntryModel.event_id == event_id,
                WaitlistEntryModel.user_id == user_id,
                WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_active_waitlist_entries(self, *, event_id: int) -> list[WaitlistEntryModel]:
        result = await self.session.execute(
            select(WaitlistEntryModel)
            .where(
                WaitlistEntryModel.event_id == event_id,
                WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
            )
            .order_by(WaitlistEntryModel.position.asc(), WaitlistEntryModel.id.asc())
            .with_for_update()
        )
        return list(result.scalars().all())

    async def create_confirmed_reservation(
        self,
        *,
        event_id: int,
        user_id: int,
        source: str,
        promoted_from_waitlist_entry_id: int | None = None,
    ) -> ReservationModel:
        model = ReservationModel(
            event_id=event_id,
            user_id=user_id,
            status=ReservationStatus.CONFIRMED,
            source=source,
            promoted_from_waitlist_entry_id=promoted_from_waitlist_entry_id,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def create_waitlist_entry(self, *, event_id: int, user_id: int) -> WaitlistEntryModel:
        max_position = await self.session.scalar(
            select(func.coalesce(func.max(WaitlistEntryModel.position), 0)).where(
                WaitlistEntryModel.event_id == event_id
            )
        )
        model = WaitlistEntryModel(
            event_id=event_id,
            user_id=user_id,
            status=WaitlistStatus.ACTIVE,
            position=int(max_position or 0) + 1,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def next_waitlist_entry_for_promotion(
        self, *, event_id: int, exclude_user_ids: Sequence[int] = ()
    ) -> WaitlistEntryModel | None:
        stmt = (
            select(WaitlistEntryModel)
            .where(
                WaitlistEntryModel.event_id == event_id,
                WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
            )
            .order_by(WaitlistEntryModel.position.asc(), WaitlistEntryModel.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if exclude_user_ids:
            stmt = stmt.where(WaitlistEntryModel.user_id.not_in(tuple(exclude_user_ids)))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
