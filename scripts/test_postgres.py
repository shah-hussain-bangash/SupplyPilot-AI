"""Run acceptance checks in a new disposable PostgreSQL container only."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker',action='store_true',required=True,
                        help='Create and remove a dedicated PostgreSQL 17 container')
    parser.add_argument('--concurrency',action='store_true',help='Prove overlapping execution, reconciliation, receipt and invoice requests')
    parser.add_argument('--restore-check',action='store_true',help='Verify a dump restored into a second disposable database')
    parser.add_argument('--repository',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    backend=args.repository.resolve()/'backend'
    if not (backend/'alembic.ini').is_file():
        raise SystemExit('Repository must contain backend/alembic.ini.')
    from sqlalchemy import URL,text
    import psycopg
    from psycopg import sql as pgsql

    name='supplypilot-ci-'+uuid4().hex
    admin_password=secrets.token_hex(24)
    migrator_password=secrets.token_hex(24)
    runtime_password=secrets.token_hex(24)
    portal_password=secrets.token_hex(24)
    passed=[]
    engine=None
    container_created=False

    def docker(*parts,env=None):
        result=subprocess.run(['docker',*parts],text=True,capture_output=True,env=env)
        if result.returncode:
            raise RuntimeError('Docker operation failed: '+result.stderr.strip()[:600])
        return result.stdout.strip()

    def check(ok,label):
        if not ok:raise AssertionError(label)
        passed.append(label)
        print('PASS:',label,flush=True)

    try:
        # The password is passed through the child environment, never a command argument.
        child_env=dict(os.environ,POSTGRES_PASSWORD=admin_password)
        docker('run','--detach','--name',name,'--label','supplypilot.acceptance=disposable',
               '--env','POSTGRES_PASSWORD','--env','POSTGRES_DB=supplypilot_dev',
               '--publish','127.0.0.1::5432','postgres:17-alpine',env=child_env)
        container_created=True
        address=docker('port',name,'5432/tcp')
        if not re.fullmatch(r'127\.0\.0\.1:\d+',address):
            raise RuntimeError('Expected one local-only PostgreSQL port.')
        port=int(address.rsplit(':',1)[1])
        connection_args=dict(host='127.0.0.1',port=port,dbname='supplypilot_dev',
                             user='postgres',password=admin_password,connect_timeout=2)
        for attempt in range(30):
            try:
                with psycopg.connect(**connection_args):pass
                break
            except psycopg.OperationalError:
                if attempt==29:raise RuntimeError('Temporary PostgreSQL did not become ready.') from None
                time.sleep(1)

        with psycopg.connect(**connection_args,autocommit=True) as admin:
            for role,password in (('supplypilot_app',runtime_password),
                                  ('supplypilot_migrator',migrator_password)):
                admin.execute(pgsql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(
                    pgsql.Identifier(role),pgsql.Literal(password)))
            admin.execute("ALTER ROLE supplypilot_app SET lock_timeout TO '15s'")
            admin.execute('GRANT CONNECT ON DATABASE supplypilot_dev TO supplypilot_app,supplypilot_migrator')
            admin.execute('GRANT USAGE ON SCHEMA public TO supplypilot_app')
            admin.execute('GRANT USAGE,CREATE ON SCHEMA public TO supplypilot_migrator')
            admin.execute('ALTER DEFAULT PRIVILEGES FOR ROLE supplypilot_migrator IN SCHEMA public '
                          'GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO supplypilot_app')

        # Reuse the normal reviewed Alembic environment against this new container.
        from alembic import command
        from alembic.config import Config
        cfg=Config(str(backend/'alembic.ini'))
        with patch.dict(os.environ,{'SUPPLYPILOT_DB_PORT':str(port)}), \
             patch('getpass.getpass',return_value=migrator_password):
            command.upgrade(cfg,'0007_proc_fulfillment')

        def sql(database,query,expected_error=False):
            # Acceptance cases cannot redirect the helper to another database.
            if database!='supplypilot_dev':raise ValueError('Unexpected acceptance database')
            with psycopg.connect(**connection_args,autocommit=True) as admin:
                if expected_error:
                    try:
                        with admin.transaction():
                            admin.execute('SET LOCAL ROLE supplypilot_migrator')
                            admin.execute(query)
                        return None
                    except psycopg.Error as error:
                        return error.sqlstate
                cursor=admin.execute(query)
                rows=cursor.fetchall() if cursor.description is not None else []
            def scalar(value):
                if value is None:return ''
                if isinstance(value,bool):return 't' if value else 'f'
                return str(value)
            return '\n'.join('|'.join(scalar(v) for v in row) for row in rows)

        check(sql('supplypilot_dev','SELECT version_num FROM public.alembic_version')==
              '0007_proc_fulfillment','Fresh database applies all seven migrations')
        tables=sql('supplypilot_dev',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        check(len(tables)==14,'Fresh database contains the 14 expected tables')
        def row_hashes():
            return {t:sorted(sql('supplypilot_dev','SELECT md5(row_to_json(r)::text) FROM public.'+t+' r').splitlines()) for t in tables}

        with tempfile.TemporaryDirectory(prefix='supplypilot-ci-',ignore_cleanup_errors=True) as data:
            runtime_url=URL.create('postgresql+psycopg',username='supplypilot_app',password=runtime_password,
                host='127.0.0.1',port=port,database='supplypilot_dev')
            os.environ.update(DATABASE_URL=runtime_url.render_as_string(hide_password=False),
                DATA_DIR=data,APP_MODE='local',AUTH_MODE='local',
                DEMO_PASSWORD=portal_password,TOKEN_SECRET=secrets.token_hex(32))
            sys.path.insert(0,str(backend))
            from supplypilot import manage
            from supplypilot.db import engine as application_engine
            engine=application_engine
            manage.seed()
            before_inventory=row_hashes()
            with patch.dict(os.environ,{'SUPPLYPILOT_DB_PORT':str(port)}), \
                 patch('getpass.getpass',return_value=migrator_password):
                command.upgrade(cfg,'0008_proc_inventory')
            check(sql('supplypilot_dev','SELECT version_num FROM public.alembic_version')==
                  '0008_proc_inventory','Seeded database applies the inventory migration through Alembic')
            tables=sql('supplypilot_dev',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
            check(len(tables)==16,'Inventory upgrade creates the 16-table checkpoint')
            after_inventory=row_hashes()
            check(all(after_inventory[t]==v for t,v in before_inventory.items() if t!='alembic_version'),
                  'Inventory migration preserves every pre-existing tenant row')
            from fastapi.testclient import TestClient
            from supplypilot.main import app
            from postgres_plan_cases import prepare_plan,plan_checks
            with TestClient(app) as client:
                prepared_plan_id=prepare_plan(client,portal_password,check)
            before_plans=row_hashes()
            with patch.dict(os.environ,{'SUPPLYPILOT_DB_PORT':str(port)}), \
                 patch('getpass.getpass',return_value=migrator_password):
                command.upgrade(cfg,'0009_proc_plans')
            check(sql('supplypilot_dev','SELECT version_num FROM public.alembic_version')==
                  '0009_proc_plans','Database applies plan storage through Alembic')
            tables=sql('supplypilot_dev',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
            check(len(tables)==17,'Plan storage upgrade creates the 17-table checkpoint')
            after_plans=row_hashes()
            check(all(after_plans[t]==v for t,v in before_plans.items() if t!='alembic_version'),
                  'Plan migration preserves every pre-existing tenant row')
            check(sql('supplypilot_dev',f"SELECT count(*) FROM proc_plans WHERE id='{prepared_plan_id}' AND status='pending'")=='1',
                  'Pre-existing API plan is backfilled into its projection')
            from postgres_exception_cases import prepare_exceptions,exception_checks
            with TestClient(app) as client:
                prepared_exception_id,prepared_document_id,quarantined_document_id=prepare_exceptions(client,portal_password,check)
            before_exceptions=row_hashes()
            with patch.dict(os.environ,{'SUPPLYPILOT_DB_PORT':str(port)}), \
                 patch('getpass.getpass',return_value=migrator_password):
                command.upgrade(cfg,'0010_proc_exceptions')
            check(sql('supplypilot_dev','SELECT version_num FROM public.alembic_version')==
                  '0010_proc_exceptions','Database applies exception storage through Alembic')
            tables=sql('supplypilot_dev',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
            check(len(tables)==18,'Exception upgrade creates the 18-table checkpoint')
            after_exceptions=row_hashes()
            check(all(after_exceptions[t]==v for t,v in before_exceptions.items() if t!='alembic_version'),
                  'Exception migration preserves every pre-existing tenant row')
            check(sql('supplypilot_dev',f"SELECT count(*) FROM proc_exceptions WHERE id='{prepared_exception_id}' AND status='resolved'")=='1',
                  'Pre-existing resolved API exception is backfilled')
            before_documents=row_hashes()
            with patch.dict(os.environ,{'SUPPLYPILOT_DB_PORT':str(port)}), \
                 patch('getpass.getpass',return_value=migrator_password):
                command.upgrade(cfg,'0011_proc_documents')
            check(sql('supplypilot_dev','SELECT version_num FROM public.alembic_version')==
                  '0011_proc_documents','Database applies document storage through Alembic')
            tables=sql('supplypilot_dev',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
            check(len(tables)==20,'Document upgrade creates the 20-table checkpoint')
            after_documents=row_hashes()
            check(all(after_documents[t]==v for t,v in before_documents.items() if t!='alembic_version'),
                  'Document migration preserves every pre-existing tenant row')
            check(sql('supplypilot_dev',f"SELECT count(*) FROM proc_documents WHERE id='{prepared_document_id}' AND status='review_required'")=='1',
                  'Pre-existing reviewable API document is backfilled')
            check(sql('supplypilot_dev',f"SELECT count(*) FROM proc_documents WHERE id='{quarantined_document_id}' AND status='quarantined'")=='1',
                  'Pre-existing quarantined API document is backfilled')
            before_document_jobs=row_hashes()
            check(sql('supplypilot_dev',f"SELECT count(*) FROM records WHERE kind='job' AND data->>'document_id'='{prepared_document_id}'")=='1',
                  'Real API extraction job exists before document-job upgrade')
            with patch.dict(os.environ,{'SUPPLYPILOT_DB_PORT':str(port)}), \
                 patch('getpass.getpass',return_value=migrator_password):
                command.upgrade(cfg,'head')
            check(sql('supplypilot_dev','SELECT version_num FROM public.alembic_version')==
                  '0012_proc_document_jobs','Database applies document-job storage through Alembic')
            tables=sql('supplypilot_dev',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
            check(len(tables)==21,'Document-job upgrade creates the 21-table checkpoint')
            after_document_jobs=row_hashes()
            check(all(after_document_jobs[t]==v for t,v in before_document_jobs.items() if t!='alembic_version'),
                  'Document-job migration preserves every pre-existing tenant row')
            check(sql('supplypilot_dev',f"SELECT count(*) FROM proc_document_jobs j JOIN records r ON r.tenant=j.tenant AND r.id=j.id WHERE j.document_id='{prepared_document_id}' AND j.state='completed' AND j.result=r.data::jsonb->'result' AND j.source_revision=r.revision")=='1',
                  'Pre-existing API extraction job backfills its complete result and revision')
            tenant_tables=[t for t in tables if t!='alembic_version']
            check(sql('supplypilot_dev',"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity")=='20',
                  'All 20 tenant tables have enabled and forced RLS')
            with engine.connect() as runtime:
                role=runtime.execute(text('SELECT current_user')).scalar_one()
                check(role=='supplypilot_app','Workflow uses the restricted runtime role')
                for table in tenant_tables:
                    check(runtime.execute(text('SELECT count(*) FROM public.'+table)).scalar_one()==0,
                          table+' denies reads without tenant context')
                for table in [t for t in tenant_tables if t.startswith('proc_')]:
                    check(not runtime.execute(text("SELECT has_table_privilege(current_user,:table,'INSERT,UPDATE,DELETE')"),{'table':'public.'+table}).scalar_one(),
                          table+' remains read-only to runtime')
                check(not runtime.execute(text("SELECT has_table_privilege(current_user,'public.audit','UPDATE,DELETE')")).scalar_one(),
                      'Audit cannot be updated or deleted by runtime')
                check(not runtime.execute(text("SELECT has_table_privilege(current_user,'public.alembic_version','SELECT,INSERT,UPDATE,DELETE')")).scalar_one(),
                      'Migration version table is protected from runtime')
            from fastapi.testclient import TestClient
            from supplypilot.main import app
            from postgres_acceptance_cases import workflow,read_checks
            with TestClient(app) as client:
                from postgres_concurrency_cases import build_race
                race=build_race(check,sql) if args.concurrency else None
                case=workflow(client,portal_password,check,race=race)
                baseline=row_hashes()
                read_checks(client,portal_password,check,sql,'supplypilot_dev')
                check(row_hashes()==baseline,'Read probes restore every synthetic checkpoint row')
            oid=case['order_id']
            check(sql('supplypilot_dev',f"SELECT status||'|'||total FROM proc_orders WHERE id='{oid}'")=='closed|7250.00',
                  'Relational order remains closed at AED 7250')
            check(sql('supplypilot_dev',f"SELECT count(*),sum(accepted),sum(rejected),sum(quarantine) FROM proc_receipts WHERE order_id='{oid}'")=='2|55|0|0',
                  'Receipt ledger retains 55 accepted pieces')
            check(sql('supplypilot_dev',f"SELECT count(*),sum(quantity) FROM proc_invoices WHERE order_id='{oid}' AND status='matched'")=='2|55',
                  'Invoice ledger retains two matched invoices for 55 pieces')
            if args.concurrency:
                iid=case['intent_id']
                check(sql('supplypilot_dev',f"SELECT count(*) FROM outbox WHERE id='{iid}' AND state='confirmed'")=='1',
                      'Concurrent execution retains exactly one confirmed intent')
                check(sql('supplypilot_dev',f"SELECT count(*) FROM proc_orders WHERE intent_id='{iid}'")=='1',
                      'Concurrent reconciliation creates exactly one order projection')
                check(sql('supplypilot_dev',f"SELECT count(*) FROM audit WHERE action='order.created' AND resource='{oid}'")=='1',
                      'Concurrent reconciliation records one order-created audit event')
                check(sql('supplypilot_dev',f"SELECT count(*) FROM audit WHERE action='order.receipt_recorded' AND resource='{oid}'")=='2',
                      'Rejected receipt request adds no extra receipt audit event')
                check(sql('supplypilot_dev',f"SELECT count(*) FROM audit WHERE action='order.invoice_reviewed' AND resource='{oid}'")=='2',
                      'Rejected invoice request adds no extra invoice audit event')
            from postgres_inventory_cases import inventory_checks
            inventory_checks(sql,dict(connection_args,user='supplypilot_app',password=runtime_password),check)
            plan_checks(sql,dict(connection_args,user='supplypilot_app',password=runtime_password),check)
            exception_checks(sql,dict(connection_args,user='supplypilot_app',password=runtime_password),check)
            from postgres_document_cases import document_checks
            document_checks(sql,dict(connection_args,user='supplypilot_app',password=runtime_password),check)
            from postgres_document_job_cases import document_job_checks
            document_job_checks(sql,dict(connection_args,user='supplypilot_app',password=runtime_password),check)
            if args.restore_check:
                from postgres_restore_cases import restore_checks
                restore_checks(docker,name,connection_args,runtime_password,check,case)
            engine.dispose();engine=None
        if args.report:
            args.report.write_text(json.dumps({'result':'passed','checks_passed':len(passed),
                'checks':passed,'revision':'0012_proc_document_jobs',
                'database_scope':'new disposable PostgreSQL 17 container; synthetic data only',
                'concurrency_checked':args.concurrency,'restore_checked':args.restore_check,'inventory_checked':True,'plan_storage_checked':True,'exception_storage_checked':True,'document_storage_checked':True,'document_job_storage_checked':True},indent=2),encoding='utf-8')
        print('POSTGRESQL ACCEPTANCE PASSED')
        print('Checks passed:',len(passed))
    finally:
        if engine is not None:engine.dispose()
        if container_created:
            docker('rm','--force',name)
            print('Removed the dedicated acceptance container.')


if __name__=='__main__':
    main()
