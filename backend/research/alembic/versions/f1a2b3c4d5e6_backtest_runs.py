"""backtest runs

Revision ID: f1a2b3c4d5e6
Revises: e8b9c0d1f2a3
Create Date: 2026-11-05 23:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e8b9c0d1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_runs_listing_id", "backtest_runs", ["listing_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_listing_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
