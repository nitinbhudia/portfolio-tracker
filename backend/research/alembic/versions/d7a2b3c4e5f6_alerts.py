"""in-app alerts and per-listing evaluation state

Revision ID: d7a2b3c4e5f6
Revises: c4e1f2a9b801
Create Date: 2026-11-05 22:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "d7a2b3c4e5f6"
down_revision = "c4e1f2a9b801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "key", "bar_date", name="uq_alerts_listing_key_bar"),
    )
    op.create_index("ix_alerts_listing_id", "alerts", ["listing_id"])
    op.create_table(
        "alert_state",
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("last_bar_date", sa.Date(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"]),
        sa.PrimaryKeyConstraint("listing_id"),
    )


def downgrade() -> None:
    op.drop_table("alert_state")
    op.drop_index("ix_alerts_listing_id", table_name="alerts")
    op.drop_table("alerts")
