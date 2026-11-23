"""Advanced staff management: permission overrides, weekly schedules, attendance & leave enrichment

Revision ID: 7f6a8b9c0d1e
Revises: 6e5f7a8b9c0d
Create Date: 2026-11-23 10:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "7f6a8b9c0d1e"
down_revision = "6e5f7a8b9c0d"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table_name)}
    if column.name not in cols:
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing(
        "staff_profiles",
        sa.Column("availability_status", sa.String(length=32), nullable=False, server_default="available"),
    )
    _add_column_if_missing(
        "staff_profiles",
        sa.Column("weekly_hours_target", sa.Integer(), nullable=False, server_default="48"),
    )

    _add_column_if_missing(
        "staff_shifts",
        sa.Column("is_weekly_recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing("staff_shifts", sa.Column("notes", sa.String(length=255), nullable=True))

    _add_column_if_missing("staff_attendance", sa.Column("end_date", sa.Date(), nullable=True))
    _add_column_if_missing(
        "staff_attendance",
        sa.Column("leave_type", sa.String(length=32), nullable=False, server_default="casual"),
    )
    _add_column_if_missing(
        "staff_attendance",
        sa.Column("approval_status", sa.String(length=32), nullable=False, server_default="approved"),
    )
    _add_column_if_missing("staff_attendance", sa.Column("worked_minutes", sa.Integer(), nullable=True))
    _add_column_if_missing("staff_attendance", sa.Column("review_notes", sa.String(length=255), nullable=True))

    if not _table_exists("user_permissions"):
        op.create_table(
            "user_permissions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("permission_id", sa.UUID(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id", name="pk_user_permissions"),
            sa.UniqueConstraint("user_id", "permission_id", name="uq_user_permissions_pair"),
        )
        op.create_index("ix_user_permissions_user_id", "user_permissions", ["user_id"], if_not_exists=True)
        op.create_index("ix_user_permissions_permission_id", "user_permissions", ["permission_id"], if_not_exists=True)

    if not _table_exists("staff_weekly_schedules"):
        op.create_table(
            "staff_weekly_schedules",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("staff_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", sa.UUID(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("counter_id", sa.UUID(), sa.ForeignKey("counters.id", ondelete="SET NULL"), nullable=True),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.Column("shift_type", sa.String(length=32), nullable=False, server_default="regular"),
            sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id", name="pk_staff_weekly_schedules"),
            sa.UniqueConstraint(
                "staff_user_id",
                "canteen_id",
                "day_of_week",
                "shift_type",
                name="uq_staff_weekly_sched",
            ),
        )
        op.create_index(
            "ix_staff_weekly_schedules_staff_user_id",
            "staff_weekly_schedules",
            ["staff_user_id"],
            if_not_exists=True,
        )
        op.create_index(
            "ix_staff_weekly_schedules_canteen_id",
            "staff_weekly_schedules",
            ["canteen_id"],
            if_not_exists=True,
        )


def downgrade() -> None:
    if _table_exists("staff_weekly_schedules"):
        op.drop_index("ix_staff_weekly_schedules_canteen_id", table_name="staff_weekly_schedules", if_exists=True)
        op.drop_index("ix_staff_weekly_schedules_staff_user_id", table_name="staff_weekly_schedules", if_exists=True)
        op.drop_table("staff_weekly_schedules")

    if _table_exists("user_permissions"):
        op.drop_index("ix_user_permissions_permission_id", table_name="user_permissions", if_exists=True)
        op.drop_index("ix_user_permissions_user_id", table_name="user_permissions", if_exists=True)
        op.drop_table("user_permissions")

    op.drop_column("staff_attendance", "review_notes")
    op.drop_column("staff_attendance", "worked_minutes")
    op.drop_column("staff_attendance", "approval_status")
    op.drop_column("staff_attendance", "leave_type")
    op.drop_column("staff_attendance", "end_date")

    op.drop_column("staff_shifts", "notes")
    op.drop_column("staff_shifts", "is_weekly_recurring")

    op.drop_column("staff_profiles", "weekly_hours_target")
    op.drop_column("staff_profiles", "availability_status")
