"""mission index table

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mission_id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("map_name", sa.String(length=60), nullable=False),
        sa.Column("mission_type", sa.String(length=50), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("minimum_players", sa.Integer(), nullable=False),
        sa.Column("maximum_players", sa.Integer(), nullable=False),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("mission_maker", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("factions", sa.JSON(), nullable=False),
        sa.Column("required_mods", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("directory", sa.String(length=255), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_missions")),
    )
    op.create_index(op.f("ix_missions_mission_id"), "missions", ["mission_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_missions_mission_id"), table_name="missions")
    op.drop_table("missions")
