"""add config_mtime_baseline to cruise

Revision ID: d2e3f4a5b6c7
Revises: c1e2f3a4b5d6
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c7"
down_revision = "c1e2f3a4b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cruise", sa.Column("config_mtime_baseline", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("cruise", "config_mtime_baseline")
