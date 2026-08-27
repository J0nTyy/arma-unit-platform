"""AI usage tracking (daily token counters)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage_daily")),
        sa.UniqueConstraint(
            "day", "provider", "model", name=op.f("uq_ai_usage_day_provider_model")
        ),
    )
    op.create_index(op.f("ix_ai_usage_daily_day"), "ai_usage_daily", ["day"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_usage_daily_day"), table_name="ai_usage_daily")
    op.drop_table("ai_usage_daily")
