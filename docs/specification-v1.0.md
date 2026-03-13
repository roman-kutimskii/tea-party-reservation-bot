# Tea Party Reservation Bot Specification v1.0

## Document Status

- Status: Approved baseline for implementation planning
- Version: 1.0
- Scope: MVP baseline and delivery plan
- Language of product UX: Russian only
- Implementation status: Not started

## 1. Executive Summary

This document is the source of truth for building a Telegram bot for a single-location Chinese tea house that publishes tasting events and accepts registrations directly through Telegram.

The system must let administrators create one or more event drafts from structured text, validate and preview them, require explicit confirmation, and publish them to a Telegram group. Visitors must be able to register for specific events through the bot, receive immediate confirmation when seats are available, join a waitlist when events are full, cancel before the allowed deadline, and optionally subscribe to announcements about newly published tastings.

The system must be production-ready, maintainable, typed, testable, and deployable on a plain VPS with Docker, using Python 3.14, aiogram 3, and PostgreSQL.

The most critical technical guarantee is anti-overbooking under concurrent sign-ups. This must be enforced by PostgreSQL transactions, row-level locking, constraints, and idempotent command handling.

## 2. Product Overview

### 2.1 Business Goals

- Replace manual event registration handled by managers.
- Reduce admin effort for weekly event publication.
- Provide self-service registration for visitors.
- Prevent overbooking and keep seat inventory accurate.
- Support waitlists and self-service cancellations.
- Keep the solution simple enough for a small business and robust enough for production.

### 2.2 Primary Actors

- Visitor
  - Browses events.
  - Registers for an event.
  - Joins a waitlist.
  - Cancels own registration before the deadline.
  - Opts in or out of new-event notifications.
- Viewer Admin
  - Views events and participant lists.
- Registration Manager
  - Manages participant lists and operational registration changes.
- Event Manager
  - Creates drafts, edits events, publishes group announcement posts, manages registrations.
- Owner
  - Full permissions, including admin role management and configuration.

### 2.3 Role and Permission Model

Approved MVP role model:

- `owner`
- `manager`

MVP note:

- `owner` has full permissions, including admin role management and system settings.
- `manager` can create and publish events, manage registrations, and perform operational event edits.
- `viewer` and `registration_manager` remain valid future extensions, but they are not required in MVP.

Extended production-ready role model for future growth:

| Permission | Owner | Event Manager | Registration Manager | Viewer |
|---|---:|---:|---:|---:|
| View events and participants | Yes | Yes | Yes | Yes |
| Create event draft | Yes | Yes | No | No |
| Edit draft before publish | Yes | Yes | No | No |
| Publish to group | Yes | Yes | No | No |
| Create weekly batch post | Yes | Yes | No | No |
| Edit published event | Yes | Yes | Limited | No |
| Open or close registration | Yes | Yes | Limited | No |
| Change capacity | Yes | Yes | Limited | No |
| Add or remove participant manually | Yes | Yes | Yes | No |
| Move between confirmed and waitlist | Yes | Yes | Yes | No |
| Override cancellation deadline operationally | Yes | Yes | Yes | No |
| Cancel event | Yes | Yes | No | No |
| Manage admin roles | Yes | No | No | No |
| View audit log | Yes | Yes | Limited | No |
| Manage system settings | Yes | No | No | No |

Notes:

- `Limited` means operational edits only, not system-level configuration or role management.
- Telegram `user_id` is the only trusted identity for admin authorization.
- Role checks must be enforced in both Telegram handlers and application services.

### 2.4 Success Criteria

- Admins can create valid event drafts from structured text.
- Publication requires explicit admin confirmation.
- The bot can publish either a single-event post or a multi-event weekly batch post.
- Each published event can be opened from the group post and registered for individually.
- Confirmed registrations never exceed event capacity, including under concurrency.
- Full events offer a waitlist.
- Users can cancel before the effective cancellation deadline.
- Admins can manually adjust event and registration data.
- The system is deployable, observable, tested, and backed up.

### 2.5 In Scope

- One Telegram bot.
- One tea house location.
- One Telegram group for publication and announcement posting.
- Russian-only bot UX.
- Multiple admins with roles.
- Structured admin event input.
- Draft preview and explicit publish confirmation.
- Single-event and weekly batch publication.
- Visitor registration and self-cancellation.
- Waitlist with automatic promotion.
- Optional subscription to new event announcements.
- PostgreSQL persistence.
- Dockerized VPS deployment.
- CI/CD and Infrastructure as Code.
- Logging, metrics, migrations, linting, typing, and testing.

### 2.6 Out of Scope for MVP

- Payments or deposits.
- Plus-one or multi-seat visitor bookings.
- Multi-location support.
- Multilingual UI.
- CRM integration.
- Attendance check-in.
- Advanced analytics dashboard.
- Approval-based moderation of registrations.
- AI or free-form admin text interpretation.

## 3. Functional Requirements

### 3.1 Admin Flows

- Admin access is granted by Telegram `user_id` stored in the database.
- Admin can request the structured input template.
- Admin can create:
  - one event draft; or
  - several event drafts in one batch input.
- Bot validates each draft and produces either:
  - field-specific validation errors; or
  - normalized preview output.
- Bot must show a final preview before publication.
- Admin must explicitly confirm publication.
- Admin can cancel or revise a draft before publication.
- Admin can view event roster and waitlist.
- Admin can manually add, remove, cancel, or move a participant.
- Admin can edit event details after publication.
- Admin can close or reopen registration.
- Admin can cancel an event.

### 3.2 Visitor Flows

- Visitor starts bot with `/start` or event deep link from group post.
- Visitor sees event details and can register.
- Visitor receives immediate status:
  - confirmed; or
  - waitlisted.
- Visitor can open their active registrations.
- Visitor can cancel before the event's effective cancellation deadline.
- Visitor can enable or disable new-event notifications.

### 3.3 Registration Flow

- Each registration is tied to one specific event.
- A visitor may register for multiple different events.
- A visitor may not have more than one active registration for the same event.
- When seats are available, registration is instantly confirmed.
- When an event is full, the user can join the waitlist in MVP.
- Registration is blocked when:
  - event is not published;
  - registration is closed;
  - event has started;
  - user already has an active registration for the event.

### 3.4 Waitlist Flow

- Waitlist is event-specific.
- Waitlist is enabled by default for all MVP events.
- Waitlist order is FIFO by default.
- A user may not have more than one active waitlist entry for the same event.
- When a confirmed seat becomes free, the next waitlisted user is promoted automatically.
- Promotion and seat reassignment must be atomic.
- Promoted user receives a Telegram notification.
- MVP does not use temporary seat-hold offers.
- Per-event disabling of waitlist is out of scope for MVP.

### 3.5 Cancellation Flow

- The system has a configurable default cancellation policy for MVP.
- Each event computes an effective `cancel_deadline_at` during creation.
- Admin may optionally override the default deadline for an individual event.
- Visitor self-cancellation is allowed only on or before the effective deadline.
- Visitor self-cancellation is blocked after the deadline.
- Admins with sufficient role may override the deadline operationally.
- Cancelling a confirmed registration releases the seat and may trigger waitlist promotion.

### 3.6 Notification and Subscription Flow

- Transactional notifications are sent for:
  - confirmed registration;
  - waitlist joined;
  - waitlist promotion;
  - registration cancellation;
  - event changes affecting registered users;
  - event cancellation.
- Optional non-transactional notification:
  - newly announced tastings.
- Subscription model for MVP:
  - one global on/off switch for new tasting announcements.

### 3.7 Group Posting Flow

- Bot supports:
  - standalone single-event group post;
  - weekly batch group post containing several events.
- Weekly batch group post format:
  - one combined text post;
  - clearly separated event blocks;
  - one distinct registration button per event.
- Each button must open the bot for the exact event it belongs to.
- Group publication is announcement-only; registration itself happens in the bot private chat, not inside the group thread.
- Publication requires explicit admin confirmation.
- If single-event publication fails, the event remains unpublished.
- If batch publication fails, none of the included events become published.

### 3.8 Admin Adjustment and Edit Flow

- Admin can update event fields after publication.
- Admin can change capacity.
- Admin can manually add a participant.
- Admin can manually remove or cancel a participant.
- Admin can move a user from waitlist to confirmed or vice versa.
- Admin can close registration or cancel the event.
- Material changes should notify affected users.
- All such actions must be audit logged.

### 3.9 Error Cases and Edge Cases

- Duplicate Telegram updates or repeated callback taps.
- Concurrent sign-ups for the last seat.
- Event edited after users already registered.
- Admin reduces capacity below already confirmed seats.
- User blocks bot after registering.
- Group posting rights are missing or lost.
- Invalid structured admin input.
- Registration attempt after event start.
- Cancellation attempt after deadline.
- Missing Telegram username.
- Shared batch post with one wrong button mapping.

## 4. Telegram Bot UX and Conversation Design

### 4.1 UX Principles

- Russian-only UX.
- Formal but friendly tone using `Вы`.
- Short messages.
- One message should lead to one clear next action.
- Use buttons wherever possible; avoid free-text input for visitors.
- Avoid ambiguous button labels.

### 4.2 Visitor Commands

- `/start`
- `/events`
- `/my`
- `/help`
- `/cancel`

### 4.3 Visitor Main Menu

- `Ближайшие дегустации`
- `Мои записи`
- `Уведомления`
- `Как это работает`

### 4.4 Admin Commands

- `/admin`
- `/new_event`
- `/new_batch`
- `/events_admin`
- `/participants`
- `/cancel`

### 4.5 Admin Main Menu

- `Создать событие`
- `Создать неделю`
- `События`
- `Участники`

### 4.6 Visitor Registration UX

- Event cards show:
  - tea name;
  - date and time;
  - remaining seats or full state;
  - cancellation summary.
- Event actions:
  - `Записаться`
  - `Подробнее`
  - `На лист ожидания` when full
- Registration confirmation must show:
  - event name;
  - date and time;
  - one seat;
  - cancellation deadline.
- Successful result states:
  - `Вы записаны`;
  - `Вы в листе ожидания`.

### 4.7 Cancellation UX

- Cancellation requires explicit confirmation.
- If cancellation is allowed, user sees:
  - `Да, отменить`
  - `Нет, оставить`
- If blocked, bot explains the deadline rule and may suggest contacting organizer if such policy exists.

### 4.8 Waitlist UX

- Full event should offer waitlist instead of dead end.
- Join waitlist message should clearly state this is not yet a confirmed seat.
- Promotion message should clearly state that the registration is now confirmed.

### 4.9 Admin Draft and Publication UX

- Admin requests template.
- Admin submits one or more structured blocks.
- Bot validates all blocks.
- For single event:
  - show normalized preview and formatted post preview.
- For batch:
  - show normalized preview per event;
  - show final combined post preview;
  - show one button per event in preview labeling logic.
- Confirmation buttons:
  - `Опубликовать`
  - `Исправить`
  - `Отмена`

### 4.10 Error and Fallback UX

- Invalid input errors must identify fields exactly.
- Unknown free-text visitor messages should guide user back to buttons.
- If Telegram hides the keyboard, bot should suggest `/start`.

## 5. Admin Input Design

### 5.1 Recommended Single-Event Input Format

```text
Чай: <название>
Дата: <ДД.ММ.ГГГГ>
Время: <ЧЧ:ММ>
Мест: <целое число>
Отмена до: <ДД.ММ.ГГГГ ЧЧ:ММ>   # необязательно
Описание: <необязательно>
```

### 5.2 Recommended Weekly Batch Input Format

Each event is one block. Blocks are separated by `---`.

```text
Чай: Да Хун Пао
Дата: 21.03.2026
Время: 19:00
Мест: 12
Описание: Весенний открытый вечер
---
Чай: Те Гуань Инь
Дата: 23.03.2026
Время: 18:30
Мест: 10
Отмена до: 23.03.2026 12:00
Описание: Спокойная вечерняя дегустация
```

### 5.3 Parsing and Validation Rules

- Required fields per event block:
  - `Чай`
  - `Дата`
  - `Время`
  - `Мест`
- Optional fields per event block:
  - `Отмена до`
  - `Описание`
- `Дата` must be a valid date in `ДД.ММ.ГГГГ` format.
- `Время` must be valid 24-hour local time.
- `Мест` must be integer greater than zero.
- Event start must be in the future.
- If `Отмена до` is present, it must be earlier than event start.
- If `Отмена до` is missing, the system applies the default cancellation deadline policy.
- In batch mode, all blocks must be valid before publication is allowed.

### 5.4 Error Reporting

- Error responses must be field-specific.
- Example messages:
  - `Поле "Дата": нужен формат ДД.ММ.ГГГГ`
  - `Поле "Мест": только целое число больше 0`
  - `Поле "Отмена до": должно быть раньше начала события`
- In batch mode, errors must identify the exact block number and field.

### 5.5 Normalized Output Model

```json
{
  "tea_name": "Да Хун Пао",
  "starts_at_local": "2026-03-21T19:00:00+03:00",
  "starts_at_utc": "2026-03-21T16:00:00Z",
  "capacity": 12,
  "cancel_deadline_source": "default",
  "cancel_deadline_at_local": "2026-03-21T15:00:00+03:00",
  "description": "Весенний открытый вечер",
  "status": "draft"
}
```

## 6. System Architecture

### 6.1 Architectural Style

Recommended architecture: layered modular monolith.

Main components:

- `presentation.telegram`
  - aiogram routers, handlers, filters, keyboards, message rendering.
- `application`
  - use cases and transaction orchestration.
- `domain`
  - entities, policies, enums, invariants.
- `infrastructure.db`
  - SQLAlchemy models, repositories, sessions, locking helpers.
- `infrastructure.telegram`
  - Telegram API adapters and publishing code.
- `background`
  - outbox processing, retries, scheduling, reconciliation.
- optional `http`
  - health/readiness endpoint if needed.

### 6.2 Core Runtime Components

- `bot` container
  - processes Telegram updates.
- `worker` container
  - processes outbox and scheduled jobs.
- `postgres` container
  - primary data store.
- optional `caddy`
  - reverse proxy and TLS if webhooks are used.

Telegram group capability assumptions:

- The bot must be added to the target Telegram group.
- The bot must have sufficient rights to publish announcement messages in that group.
- The bot must be able to attach inline buttons or deep links to published group posts.
- The design must not rely on users interacting with the bot inside the group chat itself.
- Users are expected to open the bot from post buttons or deep links and complete registration in private chat with the bot.
- Group messages are announcement entry points, not the source of truth for registrations.

### 6.3 PostgreSQL Usage and Rationale

PostgreSQL is the single source of truth for:

- admins and roles;
- events;
- publication batches;
- registrations;
- waitlist entries;
- processed idempotency keys;
- outbox events;
- audit log.

Reasons:

- strong transactional guarantees;
- row-level locking;
- constraints and indexes;
- suitability for a small but production-grade deployment.

### 6.4 Concurrency Model

- Telegram updates may arrive concurrently.
- Multiple app instances may exist in future.
- Correctness must not rely on in-process memory locks.
- Event-level consistency must be guaranteed by PostgreSQL transactions.
- Recommended isolation level: `READ COMMITTED` with explicit row locks.

### 6.5 Transaction Boundaries and Locking Strategy

Every seat-changing mutation must run inside a database transaction.

For registration:

1. Begin transaction.
2. Lock the target event row with `SELECT ... FOR UPDATE`.
3. Re-check event status, registration openness, and user eligibility.
4. Check for existing active reservation or waitlist entry for the same user and event.
5. If seats are available:
   - insert confirmed reservation;
   - increment `reserved_seats`.
6. If seats are unavailable and waitlist is enabled:
   - insert waitlist entry.
7. Insert outbox event if notification is required.
8. Commit.

For cancellation:

1. Begin transaction.
2. Lock event row.
3. Lock reservation row.
4. Validate cancellation eligibility.
5. Mark reservation cancelled.
6. Decrement `reserved_seats`.
7. Promote next waitlist user if applicable.
8. Write outbox events.
9. Commit.

### 6.6 Anti-Overbooking Guarantee

Overbooking is prevented by combining:

- event-row locking with `FOR UPDATE`;
- transaction-scoped seat checks;
- atomic updates to `reserved_seats`;
- unique constraints preventing duplicate active reservations;
- idempotent processing of repeated Telegram updates.

Why this works:

- only one transaction can modify seat allocation for a given event at a time;
- every concurrent signup for the same event waits on the same lock;
- each transaction sees the newest committed seat count;
- once capacity is reached, later transactions cannot create more confirmed seats.

### 6.7 Idempotency Strategy

- Every mutating action uses an idempotency key derived from Telegram update or callback metadata.
- Keys are stored in `processed_commands` with a unique constraint.
- Repeated processing of the same update must not duplicate a booking, promotion, or cancellation.

### 6.8 Waitlist Promotion Logic

Recommended MVP behavior:

- automatic promotion;
- no temporary hold;
- FIFO order by `created_at` and deterministic tie-breaker by `id`.

Promotion transaction:

1. Lock event row.
2. Cancel or remove a confirmed registration.
3. Decrement `reserved_seats`.
4. Select next active waitlist entry with row-level lock.
5. Mark it promoted.
6. Create confirmed reservation.
7. Increment `reserved_seats`.
8. Write outbox notification.
9. Commit.

### 6.9 Cancellation Deadline Modeling

- System setting defines default cancellation policy for MVP.
- Recommended MVP setting: `default_cancel_deadline_offset_minutes`.
- At event creation:
  - if admin supplies `Отмена до`, use it;
  - otherwise compute from default offset and event start.
- Persist on event:
  - `cancel_deadline_at`;
  - `cancel_deadline_source` as `default` or `override`.
- Runtime logic always checks persisted `cancel_deadline_at` rather than recomputing it later.

### 6.10 Group Publishing Workflow

Single event publication:

1. Validate draft.
2. Save publish intent and outbox event in one transaction.
3. Worker sends group announcement post.
4. On success, event becomes `published_open` and stores Telegram group message metadata.

Batch publication:

1. Validate all selected drafts.
2. Create `publication_batch` and link included events in one transaction.
3. Save outbox publish event.
4. Worker sends one combined group post with clearly separated event blocks.
5. Worker attaches one distinct registration button per event.
6. On success, all included events become `published_open`.
7. On failure, none of the included events become published.

### 6.11 Admin Role Enforcement

- Presentation layer may filter unauthorized actions early.
- Application layer must enforce authorization again.
- Sensitive actions must always be audited.

## 7. Data Model

### 7.1 Main Entities

- `users`
- `roles`
- `role_assignments`
- `event_occurrences`
- `publication_batches`
- `publication_batch_events`
- `reservations`
- `waitlist_entries`
- `notification_preferences`
- `processed_commands`
- `outbox_events`
- `admin_audit_log`

### 7.2 Suggested Schema Outline

#### users

- `id` PK
- `telegram_user_id` bigint unique not null
- `username` text nullable
- `first_name` text nullable
- `last_name` text nullable
- `created_at`
- `updated_at`

#### roles

- `id` PK
- `code` text unique not null
- `description` text

#### role_assignments

- `id` PK
- `user_id` FK
- `role_id` FK
- unique `(user_id, role_id)`
- `created_at`

#### event_occurrences

- `id` PK
- `tea_name` text not null
- `description` text nullable
- `starts_at` timestamptz not null
- `timezone` text not null
- `capacity` integer not null
- `reserved_seats` integer not null default 0
- `cancel_deadline_at` timestamptz not null
- `cancel_deadline_source` text not null
- `status` text not null
- `publication_batch_id` FK nullable
- `telegram_group_chat_id` bigint nullable
- `telegram_group_message_id` bigint nullable
- `created_by_user_id` FK
- `published_at` timestamptz nullable
- `created_at`
- `updated_at`

#### publication_batches

- `id` PK
- `period_label` text nullable
- `status` text not null
- `telegram_group_chat_id` bigint nullable
- `telegram_group_message_id` bigint nullable
- `created_by_user_id` FK
- `published_at` timestamptz nullable
- `created_at`
- `updated_at`

#### publication_batch_events

- `id` PK
- `batch_id` FK
- `event_id` FK
- `sort_order` integer not null
- unique `(batch_id, event_id)`

#### reservations

- `id` PK
- `event_id` FK
- `user_id` FK
- `status` text not null
- `source` text not null
- `promoted_from_waitlist_entry_id` FK nullable
- `created_at`
- `cancelled_at` nullable
- `updated_at`

#### waitlist_entries

- `id` PK
- `event_id` FK
- `user_id` FK
- `status` text not null
- `position` bigint not null
- `created_at`
- `promoted_at` nullable
- `cancelled_at` nullable
- `updated_at`

#### notification_preferences

- `id` PK
- `user_id` FK unique
- `new_events_enabled` boolean not null default false
- `created_at`
- `updated_at`

#### processed_commands

- `id` PK
- `source` text not null
- `idempotency_key` text not null
- `result_ref` text nullable
- unique `(source, idempotency_key)`
- `created_at`

#### outbox_events

- `id` PK
- `aggregate_type` text not null
- `aggregate_id` uuid or bigint not null
- `event_type` text not null
- `payload_json` jsonb not null
- `available_at` timestamptz not null
- `sent_at` timestamptz nullable
- `attempt_count` integer not null default 0
- `last_error` text nullable
- `created_at`

#### admin_audit_log

- `id` PK
- `actor_user_id` FK
- `action` text not null
- `target_type` text not null
- `target_id` text not null
- `payload_json` jsonb not null
- `created_at`

### 7.3 Constraints, Indexes, and Uniqueness Rules

- `users.telegram_user_id` unique.
- `event_occurrences.capacity > 0`.
- `event_occurrences.reserved_seats >= 0 AND reserved_seats <= capacity`.
- `event_occurrences.cancel_deadline_at <= starts_at`.
- Partial unique index on active reservation for `(event_id, user_id)`.
- Partial unique index on active waitlist entry for `(event_id, user_id)`.
- Index `reservations(event_id, status)`.
- Index `waitlist_entries(event_id, status, position)`.
- Index `event_occurrences(status, starts_at)`.
- Index `outbox_events(sent_at, available_at)`.

### 7.4 State Transitions

Event:

- `draft`
- `ready_for_review`
- `published_open`
- `published_full`
- `registration_closed`
- `completed`
- `cancelled`

Reservation:

- `confirmed`
- `cancelled`

Waitlist entry:

- `active`
- `promoted`
- `cancelled`

Publication batch:

- `draft`
- `publishing`
- `published`
- `failed`

## 8. Non-Functional Requirements

### 8.1 Reliability

- No overbooking.
- No duplicate active reservations per user and event.
- No partial business publication of a batch.
- Service must recover after restart.

### 8.2 Security

- Telegram `user_id` based auth.
- Deny-by-default RBAC.
- No secrets in git.
- Least-privilege server access.

### 8.3 Privacy

- Store only Telegram-provided data required for operation.
- No phone collection in MVP.
- Avoid unnecessary personal data in logs.

### 8.4 Performance

- Optimize for correctness over throughput.
- Interactive response expected within a few seconds.
- Moderate concurrency around new event announcements must be handled safely.

### 8.5 Observability

- Structured JSON logs.
- Metrics for registrations, waitlist joins, promotions, cancellations, publish failures, auth denials, duplicate suppression.
- Alerting for downtime, backup failure, publish failures, DB disk pressure.

### 8.6 Backup and Recovery

- Daily PostgreSQL logical backup.
- Regular persistent volume snapshots.
- Off-VPS encrypted backup copy.
- Monthly restore drill minimum.

### 8.7 Maintainability

- Typed Python.
- Clean modular architecture.
- Validation at boundaries.
- Migrations for schema evolution.
- Linting, formatting, static typing, tests.

## 9. Delivery Architecture

### 9.1 Local Development

- Docker Compose for PostgreSQL and optional worker.
- App may run locally or in container.
- Environment-variable-based configuration.
- Migrations used in development, not schema auto-create.

### 9.2 Environment Strategy

- `local`
- `stage`
- `prod`

If only one VPS is available, `stage` may be a separate Compose project on the same host with separate secrets, bot token, and database.

### 9.3 VPS Deployment

Containers:

- `bot`
- `worker`
- `postgres`
- optional `caddy`

### 9.4 Reverse Proxy and TLS

- Recommended MVP: long polling to reduce ingress complexity.
- If webhooks are adopted later, use Caddy for TLS termination and webhook endpoint exposure.

### 9.5 Secret Management

- Secrets stored outside git.
- CI secrets in GitHub Actions secrets.
- Server secrets in restricted env files.

### 9.6 Monitoring and Alerting

- Uptime check.
- Deployment notifications.
- Backup failure alerts.
- Error-rate alerts.

## 10. Recommended Stack and Tooling

- Python `3.14`
- `aiogram 3`
- PostgreSQL
- `SQLAlchemy 2.x`
- `psycopg 3`
- `Alembic`
- `Pydantic v2`
- `pydantic-settings`
- `pytest`
- `pytest-asyncio`
- `testcontainers-python`
- `Ruff`
- `mypy`
- `structlog` or JSON stdlib logging
- `APScheduler`
- `uv`

## 11. QA Strategy

### 11.1 Test Pyramid

- Unit tests: business rules and validation.
- Integration tests: PostgreSQL transactions, constraints, repositories, migrations.
- End-to-end tests: Telegram sandbox or staging flows.

### 11.2 Critical Acceptance Scenarios

- Admin creates and publishes a valid single event.
- Admin creates and publishes a valid weekly batch post.
- Each batch button opens the correct event.
- Default cancellation deadline is applied when override is absent.
- Per-event override is respected when present.
- Visitor registers successfully when seats exist.
- Full event places later users on waitlist.
- Final seat can only be allocated once under concurrency.
- Visitor can cancel before deadline.
- Visitor cannot cancel after deadline.
- Cancelled seat promotes next waitlist user automatically.
- Unauthorized user cannot use admin actions.

### 11.3 Concurrency and Overbooking Tests

- Parallel sign-ups for last seat.
- Duplicate callback replay.
- Concurrent cancel and signup.
- Concurrent admin capacity change and signup.
- Concurrent waitlist promotions caused by multiple cancellations.

### 11.4 Batch Publication Tests

- Multi-block valid batch publish.
- Batch with one invalid block must fail cleanly.
- Correct mapping between event block and registration button.
- One event with default cancellation deadline and one with override in the same batch.

### 11.5 Operational Smoke Checks

- Publish test batch to staging group.
- Open each event via deep link.
- Register until full.
- Waitlist next user.
- Cancel one registration and verify promotion.

## 12. Security and Operational Review

### 12.1 Security Assumptions

- Telegram `user_id` is trusted as the stable identity.
- Admin authorization is DB-backed.
- Bot token is stored securely and rotated when needed.

### 12.2 Risks and Mitigations

- Overbooking risk
  - Mitigation: row locks, constraints, idempotency, transaction tests.
- Wrong event button mapping in batch post
  - Mitigation: explicit per-event deep link generation, preview, E2E tests.
- Secret leakage
  - Mitigation: strict secret handling and no tokens in logs.
- Lost message after DB commit
  - Mitigation: transactional outbox.
- Single VPS failure
  - Mitigation: tested backups, restore runbook, conservative operations.

## 13. Risks, Assumptions, and Resolved Product Decisions

### 13.1 Key Risks

- Managers continue side-channel registration outside the bot.
- Group permissions are misconfigured.
- Event edits after publication create user confusion if notifications are weak.
- Batch formatting mistakes create wrong event-to-button mapping.

### 13.2 Approved Product Decisions

- One Telegram account equals one seat per event in MVP.
- MVP admin roles are `owner` and `manager`.
- Waitlist is automatic and promoted automatically.
- Waitlist is enabled by default for all MVP events.
- New-event notifications are global on/off only.
- Group post uses one combined text post for weekly batch publication.
- Weekly batch post contains clearly separated event blocks and one distinct button per event.
- Cancellation deadline uses system default in MVP with optional per-event override.
- Registration remains event-specific even in batch posts.

### 13.3 Critical Assumptions Still Remaining

- All official seat allocation happens through the bot, not manual side channels.
- One location and one primary timezone are used consistently.
- Registration closes no later than event start unless a later requirement adds a separate registration-close field.
- Long polling is acceptable for MVP deployment.
- The Telegram group is used for announcement posts, while all actual registration actions happen in private chat with the bot.

## 14. Phased Implementation Plan

### 14.1 MVP Scope

- Project skeleton and tooling.
- Role-based admin model.
- Configurable default cancellation policy.
- Structured event draft parsing.
- Single-event and weekly batch preview/publish flow.
- Registration, waitlist, cancellation, and admin adjustments.
- Outbox-based notifications.
- Observability, testing, Docker deployment, CI/CD, and IaC.

### 14.2 Post-MVP Opportunities

- Multiple seats per booking.
- Reminder notifications.
- Attendance/check-in.
- Analytics.
- Multi-location support.
- Multilingual support.
- Hold-based waitlist offers.

### 14.3 Recommended Build Order

1. Repo/tooling foundation.
2. Configuration and settings, including default cancellation policy.
3. Schema and migrations.
4. RBAC and admin identity.
5. Single-event parsing and preview.
6. Batch parsing and preview.
7. Publication flow and outbox.
8. Registration and anti-overbooking logic.
9. Waitlist and cancellation flow.
10. Admin adjustments and audit logging.
11. Observability, staging, smoke tests, release prep.

## 15. CI/CD and IaC Specifics

### 15.1 CI Workflow

Recommended CI in GitHub Actions:

1. Checkout.
2. Install Python `3.14`.
3. Install dependencies via `uv`.
4. Run `ruff check`.
5. Run `ruff format --check`.
6. Run `mypy`.
7. Run unit tests.
8. Run integration tests against PostgreSQL service.
9. Build Docker image.
10. Run vulnerability and secret scanning.

### 15.2 CD Workflow

- On merge to `main`:
  - build immutable image;
  - push to GHCR;
  - deploy to `stage`;
  - run smoke checks.
- On release or manual approval:
  - deploy same image digest to `prod`;
  - run migrations;
  - run smoke checks.

### 15.3 Rollback Expectations

- Redeploy previous known-good image for app rollback.
- Use backward-compatible migrations where possible.
- Keep backup-and-restore runbook for migration failures.

### 15.4 Infrastructure as Code Structure

- `infra/terraform`
  - VPS, DNS, firewall, volumes, snapshot policies.
- `infra/ansible`
  - Docker host bootstrap, hardening, backup jobs, monitoring agents.
- `deploy/compose`
  - Compose files per environment.
- `ops/runbooks`
  - deploy, rollback, restore, incident response.

## 16. Source-of-Truth Notes for the Next Implementation Agent

The next implementation agent must treat this document as the authoritative baseline.

In particular:

- Do not replace PostgreSQL concurrency controls with in-memory locking.
- Do not weaken idempotency requirements.
- Do not change weekly batch publication into per-event posting only.
- Do not remove the default cancellation policy with per-event override.
- Do not add extra personal data collection in MVP.
- Do not start with plus-one or multi-seat booking in MVP.
- Keep Russian-only UX for the product.
