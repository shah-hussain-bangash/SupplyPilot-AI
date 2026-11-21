"""Create the existing application tables in a fresh PostgreSQL development database.

This compatibility baseline does not normalize procurement records or migrate SQLite data.
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_pg_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('username', sa.String(120), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('tenant', sa.String(64), nullable=False),
        sa.Column('role', sa.String(40), nullable=False),
        sa.Column('supplier_id', sa.String(64), nullable=True),
        sa.Column('authority_cents', sa.Integer(), nullable=False),
        sa.Column('active', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_users'),
        sa.UniqueConstraint('username', name='uq_users_username'),
        sa.CheckConstraint('authority_cents >= 0', name='ck_users_authority_nonnegative'),
        sa.CheckConstraint('active IN (0, 1)', name='ck_users_active_flag'),
        schema='public',
    )
    op.create_table(
        'records',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('tenant', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_records'),
        sa.CheckConstraint('revision >= 1', name='ck_records_positive_revision'),
        schema='public',
    )
    op.create_index('ix_records_tenant', 'records', ['tenant'], schema='public')
    op.create_index('ix_records_kind', 'records', ['kind'], schema='public')
    op.create_table(
        'audit',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('tenant', sa.String(64), nullable=False),
        sa.Column('actor', sa.String(64), nullable=False),
        sa.Column('action', sa.String(120), nullable=False),
        sa.Column('resource', sa.String(64), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('at', sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_audit'),
        schema='public',
    )
    op.create_index('ix_audit_tenant', 'audit', ['tenant'], schema='public')
    op.create_table(
        'outbox',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('tenant', sa.String(64), nullable=False),
        sa.Column('key', sa.String(120), nullable=False),
        sa.Column('plan_id', sa.String(64), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(30), nullable=False),
        sa.Column('external_id', sa.String(80), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_outbox'),
        sa.UniqueConstraint('tenant', 'key', name='uq_intent_key'),
        sa.CheckConstraint('attempts >= 0', name='ck_outbox_nonnegative_attempts'),
        schema='public',
    )
    op.create_index('ix_outbox_tenant', 'outbox', ['tenant'], schema='public')
    # Limit the earlier broad default grant to the actual application tables.
    op.execute('REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM supplypilot_app')
    op.execute('REVOKE UPDATE, DELETE ON TABLE public.audit FROM supplypilot_app')


def downgrade():
    # This revision is the foundation for later migrations. Data removal is not automated.
    raise RuntimeError('Baseline downgrade is disabled. Restore a reviewed development backup instead.')
