"""memory visibility and optional expiry

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_memories",
        sa.Column(
            "visibility", sa.String(length=10), server_default="unit", nullable=False
        ),
    )
    op.add_column(
        "bot_memories",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_memories", "expires_at")
    op.drop_column("bot_memories", "visibility")
