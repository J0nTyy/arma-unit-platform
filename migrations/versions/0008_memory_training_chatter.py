"""server memory, trainer role, ambient chatter toggle

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_configurations", sa.Column("trainer_role_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "guild_configurations",
        sa.Column("chatter_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "bot_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.String(length=300), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_memories")),
    )
    op.create_index(op.f("ix_bot_memories_guild_id"), "bot_memories", ["guild_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_memories_guild_id"), table_name="bot_memories")
    op.drop_table("bot_memories")
    op.drop_column("guild_configurations", "chatter_enabled")
    op.drop_column("guild_configurations", "trainer_role_id")
