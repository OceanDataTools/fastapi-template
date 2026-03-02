"""add openrvdas tables and convert timestamps to timestamptz

Revision ID: c1e2f3a4b5d6
Revises: 57dbf607eba2
Create Date: 2026-02-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1e2f3a4b5d6'
down_revision = '57dbf607eba2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Convert existing timestamp columns to timestamptz ---
    op.alter_column('apikeys', 'created_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using="created_at AT TIME ZONE 'UTC'")
    op.alter_column('apikeys', 'expires_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="expires_at AT TIME ZONE 'UTC'")
    op.alter_column('apikeys', 'last_used',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="last_used AT TIME ZONE 'UTC'")
    op.alter_column('password_reset_tokens', 'created_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using="created_at AT TIME ZONE 'UTC'")
    op.alter_column('password_reset_tokens', 'expires_at',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using="expires_at AT TIME ZONE 'UTC'")

    # --- Create OpenRVDAS tables ---
    op.create_table('cruise',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.Column('start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('config_filename', sa.String(length=255), nullable=True),
        sa.Column('loaded_time', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('last_update',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('log_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source', sa.String(length=80), nullable=True),
        sa.Column('user', sa.String(length=80), nullable=True),
        sa.Column('log_level', sa.Integer(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_log_messages_log_level'), 'log_messages', ['log_level'], unique=False)
    op.create_index(op.f('ix_log_messages_source'), 'log_messages', ['source'], unique=False)
    op.create_index(op.f('ix_log_messages_timestamp'), 'log_messages', ['timestamp'], unique=False)
    op.create_index(op.f('ix_log_messages_user'), 'log_messages', ['user'], unique=False)
    op.create_table('loggers',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('modes',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('default', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('configs',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.Column('logger_id', sa.String(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('config_json', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['logger_id'], ['loggers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_configs_logger_id'), 'configs', ['logger_id'], unique=False)
    op.create_table('logger_config_modes',
        sa.Column('config_id', sa.String(length=255), nullable=False),
        sa.Column('mode_id', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['config_id'], ['configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mode_id'], ['modes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('config_id', 'mode_id')
    )
    op.create_table('logger_config_states',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('logger_id', sa.String(length=255), nullable=True),
        sa.Column('config_id', sa.String(length=255), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('last_checked', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('running', sa.Boolean(), nullable=False),
        sa.Column('failed', sa.Boolean(), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=False),
        sa.Column('errors', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['config_id'], ['configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['logger_id'], ['loggers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_logger_config_states_config_id'), 'logger_config_states', ['config_id'], unique=False)
    op.create_index(op.f('ix_logger_config_states_logger_id'), 'logger_config_states', ['logger_id'], unique=False)
    op.create_index('uq_logger_config_state_logger', 'logger_config_states',
                    ['logger_id', 'config_id'], unique=True,
                    postgresql_where=sa.text('logger_id IS NOT NULL'))
    op.create_index('uq_logger_config_state_config_only', 'logger_config_states',
                    ['config_id'], unique=True,
                    postgresql_where=sa.text('logger_id IS NULL'))


def downgrade() -> None:
    # --- Drop OpenRVDAS tables ---
    op.drop_index('uq_logger_config_state_config_only', table_name='logger_config_states',
                  postgresql_where=sa.text('logger_id IS NULL'))
    op.drop_index('uq_logger_config_state_logger', table_name='logger_config_states',
                  postgresql_where=sa.text('logger_id IS NOT NULL'))
    op.drop_index(op.f('ix_logger_config_states_logger_id'), table_name='logger_config_states')
    op.drop_index(op.f('ix_logger_config_states_config_id'), table_name='logger_config_states')
    op.drop_table('logger_config_states')
    op.drop_table('logger_config_modes')
    op.drop_index(op.f('ix_configs_logger_id'), table_name='configs')
    op.drop_table('configs')
    op.drop_table('modes')
    op.drop_table('loggers')
    op.drop_index(op.f('ix_log_messages_user'), table_name='log_messages')
    op.drop_index(op.f('ix_log_messages_timestamp'), table_name='log_messages')
    op.drop_index(op.f('ix_log_messages_source'), table_name='log_messages')
    op.drop_index(op.f('ix_log_messages_log_level'), table_name='log_messages')
    op.drop_table('log_messages')
    op.drop_table('last_update')
    op.drop_table('cruise')

    # --- Revert timestamp columns back to naive DateTime ---
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
