"""attendance/briefing/logs/general channels; operation archiving state

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_GUILD_COLUMNS = (
    sa.Column("attendance_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("briefing_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("operation_logs_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("general_channel_id", sa.BigInteger(), nullable=True),
)

_OPERATION_COLUMNS = (
    sa.Column("brief_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("brief_message_ids", sa.JSON(), nullable=True),
    sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in _GUILD_COLUMNS:
        op.add_column("guild_configurations", column)
    for column in _OPERATION_COLUMNS:
        op.add_column("operations", column)


def downgrade() -> None:
    for column in reversed(_OPERATION_COLUMNS):
        op.drop_column("operations", column.name)
    for column in reversed(_GUILD_COLUMNS):
        op.drop_column("guild_configurations", column.name)
