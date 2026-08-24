"""drop mission player limits and mod lists; operation capacity optional

The unit has no member limit and mods are standard unit-wide, so per-mission
player ranges and required_mods leave the schema. Operation capacity becomes
optional (NULL = unlimited); the waitlist rules only engage when set.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("operations") as batch:
        batch.alter_column("max_players", existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("missions") as batch:
        batch.drop_column("minimum_players")
        batch.drop_column("maximum_players")
        batch.drop_column("required_mods")


def downgrade() -> None:
    with op.batch_alter_table("missions") as batch:
        batch.add_column(
            sa.Column("minimum_players", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("maximum_players", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("required_mods", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("operations") as batch:
        batch.alter_column(
            "max_players", existing_type=sa.Integer(), nullable=False, server_default="0"
        )
