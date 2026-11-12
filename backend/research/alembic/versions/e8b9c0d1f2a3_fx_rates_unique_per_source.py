"""fx_rates: one rate per pair, date AND source (synthetic and ECB rates can coexist)

Revision ID: e8b9c0d1f2a3
Revises: d7a2b3c4e5f6
Create Date: 2026-11-05 22:30:00

"""
from alembic import op
import sqlalchemy as sa

revision = "e8b9c0d1f2a3"
down_revision = "d7a2b3c4e5f6"
branch_labels = None
depends_on = None

COLS = "id, base, quote, date, rate, source, is_synthetic"


def _rebuild(unique_cols: list[str], name: str) -> None:
    # Copy-and-rename works the same on SQLite and PostgreSQL (the old constraint is unnamed).
    op.create_table(
        "fx_rates_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base", sa.String(length=3), nullable=False),
        sa.Column("quote", sa.String(length=3), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=10), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(*unique_cols, name=name),
    )
    op.execute(f"INSERT INTO fx_rates_new ({COLS}) SELECT {COLS} FROM fx_rates")
    op.drop_table("fx_rates")
    op.rename_table("fx_rates_new", "fx_rates")


def upgrade() -> None:
    _rebuild(["base", "quote", "date", "source"], "uq_fx_rates_pair_date_source")


def downgrade() -> None:
    op.execute("DELETE FROM fx_rates WHERE source <> 'synthetic'")
    _rebuild(["base", "quote", "date"], "uq_fx_rates_pair_date")
