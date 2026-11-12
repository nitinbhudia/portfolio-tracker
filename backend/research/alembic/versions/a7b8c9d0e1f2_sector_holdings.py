"""sector ETF holdings (Sector Rotation module)

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-11-06 08:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sector_holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("etf_ticker", sa.String(length=12), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("identifier", sa.String(length=32), nullable=True),
        sa.Column("weight_pct", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("etf_ticker", "rank", name="uq_sector_holdings_etf_rank"),
    )
    op.create_index("ix_sector_holdings_etf_ticker", "sector_holdings", ["etf_ticker"])


def downgrade() -> None:
    op.drop_index("ix_sector_holdings_etf_ticker", table_name="sector_holdings")
    op.drop_table("sector_holdings")
