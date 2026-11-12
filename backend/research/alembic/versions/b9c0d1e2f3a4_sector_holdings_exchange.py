"""sector_holdings.exchange (European holdings span many exchanges)

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-11-06 09:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "b9c0d1e2f3a4"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sector_holdings") as b:
        b.add_column(sa.Column("exchange", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sector_holdings") as b:
        b.drop_column("exchange")
