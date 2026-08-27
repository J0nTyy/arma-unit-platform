"""developer role for developer-only data (AI spend, internals)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_configurations",
        sa.Column("developer_role_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guild_configurations", "developer_role_id")
