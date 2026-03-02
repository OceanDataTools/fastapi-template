"""convert timestamp columns to timestamptz

Revision ID: a1b2c3d4e5f6
Revises: 57dbf607eba2
Create Date: 2026-02-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '57dbf607eba2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('apikeys', 'created_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using='created_at AT TIME ZONE \'UTC\'')
    op.alter_column('apikeys', 'expires_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using='expires_at AT TIME ZONE \'UTC\'')
    op.alter_column('apikeys', 'last_used',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using='last_used AT TIME ZONE \'UTC\'')
    op.alter_column('password_reset_tokens', 'created_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using='created_at AT TIME ZONE \'UTC\'')
    op.alter_column('password_reset_tokens', 'expires_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using='expires_at AT TIME ZONE \'UTC\'')


def downgrade() -> None:
    op.alter_column('password_reset_tokens', 'expires_at',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=False)
    op.alter_column('password_reset_tokens', 'created_at',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=False)
    op.alter_column('apikeys', 'last_used',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=True)
    op.alter_column('apikeys', 'expires_at',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=True)
    op.alter_column('apikeys', 'created_at',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=False)
