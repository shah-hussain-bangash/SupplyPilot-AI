"""Launch the isolated PostgreSQL development portal. No schema changes are run."""
import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
if not (BACKEND / 'supplypilot' / 'main.py').is_file():
    raise SystemExit('Development source was not found. Check the repository directory.')

result = subprocess.run(
    ['docker', 'compose', '-p', 'supplypilot-dev', '-f', 'compose.dev-db.yaml', 'port', 'db', '5432'],
    cwd=ROOT, capture_output=True, text=True,
)
if result.returncode:
    raise SystemExit('Could not read the development database port. Check Docker and the db service.')
address = result.stdout.strip()
if not address.startswith('127.0.0.1:') or not address.rsplit(':', 1)[-1].isdigit():
    raise SystemExit('Expected one local-only PostgreSQL port. Check the Compose configuration.')
port = int(address.rsplit(':', 1)[-1])
password = getpass.getpass('Enter the supplypilot_app database password: ')
url = URL.create('postgresql+psycopg', username='supplypilot_app', password=password,
                 host='127.0.0.1', port=port, database='supplypilot_dev')
engine = create_engine(url, connect_args={'connect_timeout': 10}, hide_parameters=True)
try:
    with engine.connect() as connection:
        identity = connection.execute(text('SELECT current_database(), current_user')).one()
        if tuple(identity) != ('supplypilot_dev', 'supplypilot_app'):
            raise RuntimeError('Unexpected database or account.')
        flags = connection.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        if any(flags):
            raise RuntimeError('Application account has unexpected administrative privileges.')
        if connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")):
            raise RuntimeError('Application account unexpectedly has schema CREATE privileges.')
        for table in ('users', 'records', 'outbox'):
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                if not connection.scalar(text('SELECT has_table_privilege(current_user, :table, :privilege)'), {'table': 'public.' + table, 'privilege': privilege}):
                    raise RuntimeError(f'Missing {privilege} permission on {table}.')
        for privilege in ('SELECT', 'INSERT'):
            if not connection.scalar(text('SELECT has_table_privilege(current_user, :table, :privilege)'), {'table': 'public.audit', 'privilege': privilege}):
                raise RuntimeError(f'Missing {privilege} permission on audit.')
        for privilege in ('UPDATE', 'DELETE', 'TRUNCATE'):
            if connection.scalar(text('SELECT has_table_privilege(current_user, :table, :privilege)'), {'table': 'public.audit', 'privilege': privilege}):
                raise RuntimeError(f'Unexpected {privilege} permission on audit.')
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
            if connection.scalar(text('SELECT has_table_privilege(current_user, :table, :privilege)'), {'table': 'public.alembic_version', 'privilege': privilege}):
                raise RuntimeError('Application account unexpectedly has migration-table access.')
        for table in ('users', 'records', 'outbox', 'audit'):
            if connection.scalar(text('SELECT has_table_privilege(current_user, :table, :privilege)'), {'table': 'public.' + table, 'privilege': 'TRUNCATE'}):
                raise RuntimeError(f'Unexpected TRUNCATE permission on {table}.')
        enabled = connection.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname IN ('users','records','audit','outbox') AND c.relrowsecurity AND c.relforcerowsecurity"))
        if enabled != 4:
            raise RuntimeError('Apply the tenant-isolation migration before using this launcher.')
        seeded = bool(connection.scalar(text("SELECT public.resolve_identity_tenant('buyer', true) IS NOT NULL")))
except Exception as exc:
    # Do not print a connection URL or driver diagnostic which could reveal configuration.
    raise SystemExit('Database preflight failed (' + type(exc).__name__ + '). Run the role/permission verification before continuing.') from None
finally:
    engine.dispose()

print('PostgreSQL preflight passed: runtime role, table access, protected audit and migration table.')
if not seeded:
    demo = getpass.getpass('Choose a NEW development portal password (12+ characters): ')
    confirm = getpass.getpass('Confirm the development portal password: ')
    if len(demo) < 12 or demo != confirm:
        raise SystemExit('Portal passwords must match and contain at least 12 characters. No seed was run.')
    os.environ['DEMO_PASSWORD'] = demo

# Override inherited settings before importing the application.
os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
os.environ['DATA_DIR'] = str(BACKEND / 'data-postgres')
os.environ['APP_MODE'] = 'local'
os.environ['AUTH_MODE'] = 'local'
os.environ['WORKER_TENANTS'] = 'demo,other'
os.environ['TOKEN_SECRET'] = secrets.token_hex(32)
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))
from supplypilot.manage import seed
if not seeded:
    seed()
else:
    print('Existing development accounts preserved. Use their existing portal password.')
os.environ.pop('DEMO_PASSWORD', None)
print('Starting isolated development portal. Open the exact URL printed by Uvicorn.')
print('Database: supplypilot_dev | account: supplypilot_app | ERP: local simulator')
print('Keep this terminal open. Ctrl+C stops this development server. Restarting requires a fresh login.')
import uvicorn
uvicorn.run('supplypilot.main:app', host='127.0.0.1', port=0)
