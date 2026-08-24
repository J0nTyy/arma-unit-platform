"""initial schema: guild configurations

Revision ID: 0001
Revises:
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guild_configurations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("guild_name", sa.String(length=200), nullable=False),
        sa.Column(
            "configured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guild_configurations")),
    )
    op.create_index(
        op.f("ix_guild_configurations_guild_id"),
        "guild_configurations",
        ["guild_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_guild_configurations_guild_id"), table_name="guild_configurations")
    op.drop_table("guild_configurations")
