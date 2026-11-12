"""real market data: listing namespace, adjusted bars, provider request log

Revision ID: 7a1c0de5f001
Revises: 365705476ffa
"""
import sqlalchemy as sa
from alembic import op

revision = "7a1c0de5f001"
down_revision = "365705476ffa"
branch_labels = None
depends_on = None

# The Phase 1 unique constraint on listings was unnamed; this convention lets SQLite batch mode drop it.
NC = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    with op.batch_alter_table("listings", naming_convention=NC) as b:
        b.add_column(sa.Column("namespace", sa.String(16), nullable=False, server_default="synthetic"))
        b.add_column(sa.Column("provider_symbol", sa.String(32), nullable=True))
        b.drop_constraint("uq_listings_exchange_mic", type_="unique")
        b.create_unique_constraint("uq_listings_ns_mic_ticker", ["namespace", "exchange_mic", "ticker"])
    with op.batch_alter_table("price_bars") as b:
        b.add_column(sa.Column("adjustment", sa.String(24), nullable=False, server_default="none"))
        b.add_column(sa.Column("raw_close", sa.Numeric(20, 6), nullable=True))
        b.add_column(sa.Column("raw_volume", sa.Integer(), nullable=True))
        b.add_column(sa.Column("div_cash", sa.Numeric(20, 6), nullable=True))
        b.add_column(sa.Column("split_factor", sa.Numeric(20, 10), nullable=True))
    op.create_table(
        "provider_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_provider_requests_provider", "provider_requests", ["provider"])
    op.create_index("ix_provider_requests_at", "provider_requests", ["at"])


def downgrade():
    op.drop_index("ix_provider_requests_at", "provider_requests")
    op.drop_index("ix_provider_requests_provider", "provider_requests")
    op.drop_table("provider_requests")
    with op.batch_alter_table("price_bars") as b:
        for c in ("split_factor", "div_cash", "raw_volume", "raw_close", "adjustment"):
            b.drop_column(c)
    with op.batch_alter_table("listings") as b:
        b.drop_constraint("uq_listings_ns_mic_ticker", type_="unique")
        b.create_unique_constraint("uq_listings_exchange_mic", ["exchange_mic", "ticker"])
        b.drop_column("provider_symbol")
        b.drop_column("namespace")
