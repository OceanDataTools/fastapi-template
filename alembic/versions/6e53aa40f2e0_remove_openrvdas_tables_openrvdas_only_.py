"""remove openrvdas tables (openrvdas-only schema)

The tables created by c1e2f3a4b5d6 (cruise, loggers, configs, modes,
logger_config_modes, logger_config_states, last_update, log_messages) are
OpenRVDAS-specific and belong only on the openrvdas/openrvdas_dev branches
(see app/models_openrvdas.py there). They were only ever inert dead weight
on main/dev -- no generic-template code reads or writes them -- and their
presence without matching main/dev models made `alembic revision
--autogenerate` on main/dev propose dropping them (see issue #12). This
drops them from main/dev while leaving the (generic, unrelated) timestamptz
conversion from c1e2f3a4b5d6 in place.

Revision ID: 6e53aa40f2e0
Revises: c1e2f3a4b5d6
Create Date: 2026-09-13 10:41:50.913903

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e53aa40f2e0'
down_revision = 'c1e2f3a4b5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    # --- Recreate OpenRVDAS tables ---
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
