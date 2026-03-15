from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260315_0002"
down_revision = "20260313_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_cancel_deadline_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_settings")),
    )
    op.bulk_insert(
        sa.table(
            "system_settings",
            sa.column("id", sa.Integer()),
            sa.column("default_cancel_deadline_offset_minutes", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "default_cancel_deadline_offset_minutes": 240,
                "created_at": datetime.now(tz=UTC),
                "updated_at": datetime.now(tz=UTC),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("system_settings")
