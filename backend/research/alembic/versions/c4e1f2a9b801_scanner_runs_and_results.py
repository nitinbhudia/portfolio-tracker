"""opportunity scanner runs and results

Revision ID: c4e1f2a9b801
Revises: 7a1c0de5f001
Create Date: 2026-11-05 21:30:00

"""
from alembic import op
import sqlalchemy as sa

revision = "c4e1f2a9b801"
down_revision = "7a1c0de5f001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("atr_multiple", sa.Float(), nullable=False),
        sa.Column("setups_version", sa.String(length=32), nullable=False),
        sa.Column("score_version", sa.String(length=8), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("scanned", sa.Integer(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scan_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("triggered", sa.JSON(), nullable=False),
        sa.Column("row", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["scan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "listing_id"),
    )
    op.create_index("ix_scan_results_run_id", "scan_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_results_run_id", table_name="scan_results")
    op.drop_table("scan_results")
    op.drop_table("scan_runs")
