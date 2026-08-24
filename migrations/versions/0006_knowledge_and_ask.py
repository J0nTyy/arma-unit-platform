"""knowledge document index; AI ask channel

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_configurations", sa.Column("ask_channel_id", sa.BigInteger(), nullable=True)
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_path", sa.String(length=255), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
    )
    op.create_index(
        op.f("ix_knowledge_documents_slug"), "knowledge_documents", ["slug"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_documents_slug"), table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_column("guild_configurations", "ask_channel_id")
