"""Tenant RLS on the four tenant-bearing tables, with narrow identity bootstrap."""
from alembic import op

revision = '0002_tenant_rls'
down_revision = '0001_pg_baseline'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('users', 'records', 'audit', 'outbox'):
        op.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY')
        op.execute(f"""CREATE POLICY tenant_scope ON public.{table} TO supplypilot_app
            USING (tenant = NULLIF(current_setting('supplypilot.tenant', true), ''))
            WITH CHECK (tenant = NULLIF(current_setting('supplypilot.tenant', true), ''))""")
        op.execute(f"""CREATE POLICY migration_owner ON public.{table} TO supplypilot_migrator
            USING (true) WITH CHECK (true)""")
    op.execute("""CREATE FUNCTION public.resolve_identity_tenant(identity text, by_username boolean)
        RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT u.tenant::text FROM public.users u
          WHERE u.active=1 AND
            (($2=true AND u.username=$1) OR ($2=false AND u.id=$1))
          LIMIT 1
        $$""")
    op.execute('REVOKE ALL ON FUNCTION public.resolve_identity_tenant(text, boolean) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.resolve_identity_tenant(text, boolean) TO supplypilot_app')


def downgrade():
    op.execute('DROP FUNCTION public.resolve_identity_tenant(text, boolean)')
    for table in ('users', 'records', 'audit', 'outbox'):
        op.execute(f'DROP POLICY tenant_scope ON public.{table}')
        op.execute(f'DROP POLICY migration_owner ON public.{table}')
        op.execute(f'ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY')
