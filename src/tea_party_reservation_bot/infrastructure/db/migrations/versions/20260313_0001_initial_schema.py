from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260313_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_users_telegram_user_id")),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
    )
    op.create_table(
        "processed_commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processed_commands")),
        sa.UniqueConstraint("source", "idempotency_key", name=op.f("uq_processed_commands_source")),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_sent_at_available_at",
        "outbox_events",
        ["sent_at", "available_at"],
        unique=False,
    )
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_assignments_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_role_assignments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_assignments")),
        sa.UniqueConstraint("user_id", "role_id", name=op.f("uq_role_assignments_user_id")),
    )
    op.create_table(
        "publication_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_label", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("telegram_group_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_group_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_publication_batches_created_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_batches")),
    )
    op.create_table(
        "event_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tea_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("reserved_seats", sa.Integer(), nullable=False),
        sa.Column("cancel_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_deadline_source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("publication_batch_id", sa.Integer(), nullable=True),
        sa.Column("telegram_group_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_group_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cancel_deadline_at <= starts_at",
            name=op.f("ck_event_occurrences_cancel_deadline_before_start"),
        ),
        sa.CheckConstraint("capacity > 0", name=op.f("ck_event_occurrences_capacity_positive")),
        sa.CheckConstraint(
            "reserved_seats >= 0", name=op.f("ck_event_occurrences_reserved_seats_non_negative")
        ),
        sa.CheckConstraint(
            "reserved_seats <= capacity",
            name=op.f("ck_event_occurrences_reserved_seats_not_over_capacity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_event_occurrences_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_batch_id"],
            ["publication_batches.id"],
            name=op.f("fk_event_occurrences_publication_batch_id_publication_batches"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_occurrences")),
    )
    op.create_index(
        "ix_event_occurrences_status_starts_at",
        "event_occurrences",
        ["status", "starts_at"],
        unique=False,
    )
    op.create_table(
        "publication_batch_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["publication_batches.id"],
            name=op.f("fk_publication_batch_events_batch_id_publication_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event_occurrences.id"],
            name=op.f("fk_publication_batch_events_event_id_event_occurrences"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_batch_events")),
        sa.UniqueConstraint(
            "batch_id", "event_id", name=op.f("uq_publication_batch_events_batch_id")
        ),
    )
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event_occurrences.id"],
            name=op.f("fk_waitlist_entries_event_id_event_occurrences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_waitlist_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waitlist_entries")),
    )
    op.create_index(
        "ix_waitlist_entries_event_id_status_position",
        "waitlist_entries",
        ["event_id", "status", "position"],
        unique=False,
    )
    op.create_index(
        "uq_waitlist_entries_event_id_user_id_active",
        "waitlist_entries",
        ["event_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("promoted_from_waitlist_entry_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event_occurrences.id"],
            name=op.f("fk_reservations_event_id_event_occurrences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["promoted_from_waitlist_entry_id"],
            ["waitlist_entries.id"],
            name=op.f("fk_reservations_promoted_from_waitlist_entry_id_waitlist_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reservations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
    )
    op.create_index(
        "ix_reservations_event_id_status", "reservations", ["event_id", "status"], unique=False
    )
    op.create_index(
        "uq_reservations_event_id_user_id_active",
        "reservations",
        ["event_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'confirmed'"),
    )
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("new_events_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint("user_id", name=op.f("uq_notification_preferences_user_id")),
    )
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_admin_audit_log_actor_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_log")),
    )

    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("code", sa.Text()),
            sa.column("description", sa.Text()),
        ),
        [
            {"code": "owner", "description": "Full access"},
            {"code": "manager", "description": "Event and registration management"},
        ],
    )


def downgrade() -> None:
    op.drop_table("admin_audit_log")
    op.drop_table("notification_preferences")
    op.drop_index("uq_waitlist_entries_event_id_user_id_active", table_name="waitlist_entries")
    op.drop_index("ix_waitlist_entries_event_id_status_position", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
    op.drop_index("uq_reservations_event_id_user_id_active", table_name="reservations")
    op.drop_index("ix_reservations_event_id_status", table_name="reservations")
    op.drop_table("reservations")
    op.drop_table("publication_batch_events")
    op.drop_index("ix_event_occurrences_status_starts_at", table_name="event_occurrences")
    op.drop_table("event_occurrences")
    op.drop_table("publication_batches")
    op.drop_table("role_assignments")
    op.drop_index("ix_outbox_events_sent_at_available_at", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("processed_commands")
    op.drop_table("roles")
    op.drop_table("users")
