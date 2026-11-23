"""Synthetic pg_dump/pg_restore parity checks in the runner-owned container.

Roles are reused inside the disposable cluster; this is not a full environment recovery.
"""
from uuid import uuid4
import psycopg
from psycopg import sql


def restore_checks(docker,container,admin_args,runtime_password,check,case):
    # Every database command targets the runner's new, uniquely named container.
    if not container.startswith('supplypilot-ci-') or admin_args['dbname']!='supplypilot_dev':
        raise ValueError('Restore checks require the dedicated acceptance container')
    source='supplypilot_dev'
    restored='supplypilot_ci_restore_'+uuid4().hex
    archive='/tmp/supplypilot-acceptance-'+uuid4().hex+'.dump'

    def rows(database,query,params=None):
        if database not in (source,restored):raise ValueError('Unexpected restore database')
        with psycopg.connect(**dict(admin_args,dbname=database)) as admin:
            return admin.execute(query,params).fetchall()

    def inventory(database):
        return [r[0] for r in rows(database,
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]

    def table_hashes(database,tables):
        return {table:rows(database,sql.SQL('SELECT md5(row_to_json(r)::text) FROM public.{} r ORDER BY 1').format(
            sql.Identifier(table))) for table in tables}

    tables=inventory(source)
    before=table_hashes(source,tables)
    definitions={label:rows(source,query) for label,query in CATALOG_CHECKS.items()}
    expected_counts={(tenant,table):rows(source,
        sql.SQL('SELECT count(*) FROM public.{} WHERE tenant=%s').format(sql.Identifier(table)),
        (tenant,))[0][0] for tenant in ('demo','other') for table in tables if table!='alembic_version'}
    docker('exec',container,'pg_dump','-U','postgres','--format=custom','--file='+archive,source)
    archive_hash=docker('exec',container,'sha256sum',archive).split()[0]
    docker('exec',container,'createdb','-U','postgres','--template=template0',restored)
    docker('exec',container,'pg_restore','-U','postgres','--exit-on-error','--dbname='+restored,archive)
    check(docker('exec',container,'sha256sum',archive).split()[0]==archive_hash,
          'Synthetic dump checksum is unchanged after restore')
    check(inventory(restored)==tables,'Restore preserves the complete public table inventory')
    restored_hashes=table_hashes(restored,tables)
    for table in tables:
        check(restored_hashes[table]==before[table],table+' restores every logical row and row count')
    for label,query in CATALOG_CHECKS.items():
        check(rows(restored,query)==definitions[label],label+' restored exactly')
    check(rows(restored,'SELECT version_num FROM public.alembic_version')==[('0008_proc_inventory',)],
          'Restored database retains the migration revision')
    check(rows(restored,'SELECT status,total::text FROM public.proc_orders WHERE id=%s',
          (case['order_id'],))==[('closed','7250.00')],
          'Restored closed order retains its exact AED 7250 total')
    check(rows(restored,"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
               "WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity")==[(15,)],
          'Restored database forces RLS on all 15 tenant tables')

    runtime_args=dict(admin_args,dbname=restored,user='supplypilot_app',password=runtime_password)
    tenant_tables=[t for t in tables if t!='alembic_version']
    with psycopg.connect(**runtime_args) as runtime:
        check(runtime.execute('SELECT current_user').fetchone()==('supplypilot_app',),
              'Restored database is checked using the restricted runtime role')
        for table in tenant_tables:
            count=runtime.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table))).fetchone()[0]
            check(count==0,table+' restored RLS denies reads without tenant context')
        runtime.commit()
        for tenant in ('demo','other'):
            with runtime.transaction():
                runtime.execute("SELECT set_config('supplypilot.tenant',%s,true)",(tenant,))
                for table in tenant_tables:
                    result=runtime.execute(sql.SQL('SELECT tenant FROM public.{}').format(sql.Identifier(table))).fetchall()
                    check(len(result)==expected_counts[tenant,table] and all(r[0]==tenant for r in result),
                          table+' restored visibility is scoped to '+tenant)
            check(runtime.execute("SELECT current_setting('supplypilot.tenant',true)").fetchone()[0] in ('',None),
                  'Restored tenant context resets after '+tenant+' transaction')
            runtime.commit()
        for table in tenant_tables:
            if table.startswith('proc_'):
                allowed=runtime.execute("SELECT has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE')",
                                        ('public.'+table,)).fetchone()[0]
                check(not allowed,table+' remains read-only after restore')
        check(not runtime.execute("SELECT has_table_privilege(current_user,'public.audit','UPDATE,DELETE')").fetchone()[0],
              'Restored audit remains protected from runtime changes')
        check(not runtime.execute("SELECT has_table_privilege(current_user,'public.alembic_version','SELECT,INSERT,UPDATE,DELETE')").fetchone()[0],
              'Restored migration version table remains protected')
    check(table_hashes(source,tables)==before,'Restore drill leaves every source row unchanged')
    check(table_hashes(restored,tables)==restored_hashes,'Restored permission checks leave all restored rows unchanged')

CATALOG_CHECKS = {'Column definitions': 'SELECT '
                       "table_name,column_name,ordinal_position,data_type,udt_name,is_nullable,COALESCE(column_default,'') "
                       "FROM information_schema.columns WHERE table_schema='public' ORDER BY "
                       'table_name,ordinal_position',
 'Table owners and RLS settings': 'SELECT '
                                  'c.relname,pg_get_userbyid(c.relowner),c.relrowsecurity,c.relforcerowsecurity '
                                  'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE '
                                  "n.nspname='public' AND c.relkind='r' ORDER BY c.relname",
 'Primary keys, checks and foreign keys': 'SELECT '
                                          'c.relname,k.conname,pg_get_constraintdef(k.oid,true),k.condeferrable,k.condeferred,k.convalidated '
                                          'FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN '
                                          "pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                                          'ORDER BY c.relname,k.conname',
 'Index definitions': "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER "
                      'BY tablename,indexname',
 'RLS policy definitions': 'SELECT tablename,policyname,permissive,roles,cmd,qual,with_check FROM '
                           "pg_policies WHERE schemaname='public' ORDER BY tablename,policyname",
 'Trigger definitions and enabled state': 'SELECT '
                                          'c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true) FROM '
                                          'pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace '
                                          "n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT "
                                          't.tgisinternal ORDER BY c.relname,t.tgname',
 'Function definitions, ownership and access': 'SELECT '
                                               'p.proname,pg_get_function_identity_arguments(p.oid),pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig,p.proacl,pg_get_functiondef(p.oid) '
                                               'FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace '
                                               "WHERE n.nspname='public' AND p.prokind='f' ORDER BY "
                                               'p.proname,pg_get_function_identity_arguments(p.oid)',
 'Runtime and migrator table privileges': 'SELECT '
                                          "t.tablename,r.rolname,has_table_privilege(r.rolname,quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'SELECT'),has_table_privilege(r.rolname,quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'INSERT'),has_table_privilege(r.rolname,quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'UPDATE'),has_table_privilege(r.rolname,quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'DELETE'),has_table_privilege(r.rolname,quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'TRUNCATE') "
                                          'FROM pg_tables t CROSS JOIN pg_roles r WHERE '
                                          "t.schemaname='public' AND r.rolname IN "
                                          "('supplypilot_app','supplypilot_migrator') ORDER BY "
                                          't.tablename,r.rolname'}
