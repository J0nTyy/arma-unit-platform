"""player profiles, finalized attendance, audits, qualifications

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("join_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("onboarding_status", sa.String(length=20), nullable=False),
        sa.Column("active_status", sa.String(length=10), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("primary_role", sa.String(length=30), nullable=True),
        sa.Column("secondary_role", sa.String(length=30), nullable=True),
        sa.Column("arma_experience", sa.String(length=20), nullable=True),
        sa.Column("bio", sa.String(length=300), nullable=True),
        sa.Column("steam_id", sa.String(length=20), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_players")),
        sa.UniqueConstraint("guild_id", "discord_user_id", name=op.f("uq_players_guild_id")),
    )
    op.create_index(op.f("ix_players_guild_id"), "players", ["guild_id"])
    op.create_index(op.f("ix_players_discord_user_id"), "players", ["discord_user_id"])

    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("finalized_by", sa.BigInteger(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_records")),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["operations.id"],
            name=op.f("fk_attendance_records_operation_id_operations"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"],
            name=op.f("fk_attendance_records_player_id_players"), ondelete="CASCADE",
        ),
        sa.UniqueConstraint("operation_id", "player_id", name=op.f("uq_attendance_records_operation_id")),
    )
    op.create_index(op.f("ix_attendance_records_operation_id"), "attendance_records", ["operation_id"])
    op.create_index(op.f("ix_attendance_records_player_id"), "attendance_records", ["player_id"])

    op.create_table(
        "attendance_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(length=10), nullable=True),
        sa.Column("new_status", sa.String(length=10), nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_audits")),
        sa.ForeignKeyConstraint(
            ["record_id"], ["attendance_records.id"],
            name=op.f("fk_attendance_audits_record_id_attendance_records"), ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_attendance_audits_record_id"), "attendance_audits", ["record_id"])

    op.create_table(
        "player_qualifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("qualification", sa.String(length=30), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_qualifications")),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"],
            name=op.f("fk_player_qualifications_player_id_players"), ondelete="CASCADE",
        ),
        sa.UniqueConstraint("player_id", "qualification", name=op.f("uq_player_qualifications_player_id")),
    )
    op.create_index(op.f("ix_player_qualifications_player_id"), "player_qualifications", ["player_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_player_qualifications_player_id"), table_name="player_qualifications")
    op.drop_table("player_qualifications")
    op.drop_index(op.f("ix_attendance_audits_record_id"), table_name="attendance_audits")
    op.drop_table("attendance_audits")
    op.drop_index(op.f("ix_attendance_records_player_id"), table_name="attendance_records")
    op.drop_index(op.f("ix_attendance_records_operation_id"), table_name="attendance_records")
    op.drop_table("attendance_records")
    op.drop_index(op.f("ix_players_discord_user_id"), table_name="players")
    op.drop_index(op.f("ix_players_guild_id"), table_name="players")
    op.drop_table("players")
