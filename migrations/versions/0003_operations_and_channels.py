"""guild settings, operations, attendance, mission publications

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_GUILD_COLUMNS = (
    sa.Column("unit_name", sa.String(length=100), nullable=True),
    sa.Column("timezone", sa.String(length=64), nullable=True),
    sa.Column("reminders_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column("staff_role_id", sa.BigInteger(), nullable=True),
    sa.Column("mission_maker_role_id", sa.BigInteger(), nullable=True),
    sa.Column("operations_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("missions_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("announcements_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("logs_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("recruitment_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("aar_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("staff_channel_id", sa.BigInteger(), nullable=True),
)


def upgrade() -> None:
    for column in _GUILD_COLUMNS:
        op.add_column("guild_configurations", column)

    op.create_table(
        "operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("mission_id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("server_name", sa.String(length=100), nullable=True),
        sa.Column("max_players", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("objectives_snapshot", sa.Text(), nullable=True),
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_1h_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations")),
    )
    op.create_index(op.f("ix_operations_guild_id"), "operations", ["guild_id"])
    op.create_index(op.f("ix_operations_mission_id"), "operations", ["mission_id"])
    op.create_index(op.f("ix_operations_scheduled_at"), "operations", ["scheduled_at"])

    op.create_table(
        "operation_attendance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("waitlisted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "responded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_attendance")),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_operation_attendance_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "operation_id", "user_id", name=op.f("uq_operation_attendance_operation_id")
        ),
    )
    op.create_index(
        op.f("ix_operation_attendance_operation_id"), "operation_attendance", ["operation_id"]
    )

    op.create_table(
        "mission_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("mission_id", sa.String(length=20), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("published_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mission_publications")),
        sa.UniqueConstraint(
            "guild_id", "mission_id", "channel_id", name=op.f("uq_mission_publications_guild_id")
        ),
    )
    op.create_index(
        op.f("ix_mission_publications_guild_id"), "mission_publications", ["guild_id"]
    )
    op.create_index(
        op.f("ix_mission_publications_mission_id"), "mission_publications", ["mission_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mission_publications_mission_id"), table_name="mission_publications")
    op.drop_index(op.f("ix_mission_publications_guild_id"), table_name="mission_publications")
    op.drop_table("mission_publications")
    op.drop_index(op.f("ix_operation_attendance_operation_id"), table_name="operation_attendance")
    op.drop_table("operation_attendance")
    op.drop_index(op.f("ix_operations_scheduled_at"), table_name="operations")
    op.drop_index(op.f("ix_operations_mission_id"), table_name="operations")
    op.drop_index(op.f("ix_operations_guild_id"), table_name="operations")
    op.drop_table("operations")
    for column in reversed(_GUILD_COLUMNS):
        op.drop_column("guild_configurations", column.name)
