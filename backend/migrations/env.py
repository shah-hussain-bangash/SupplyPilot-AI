"""Development-only Alembic environment; connection secrets are not stored."""
import getpass
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import URL, create_engine, pool, text

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# Explicit reviewed migrations first. Autogeneration is intentionally unavailable.
target_metadata = None


def run_online():
    port = os.environ.get('SUPPLYPILOT_DB_PORT', '')
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise RuntimeError('Set SUPPLYPILOT_DB_PORT to the Docker development port.')
    password = getpass.getpass('Enter the supplypilot_migrator password: ')
    if not password:
        raise RuntimeError('Migration password must not be empty.')
    url = URL.create(
        'postgresql+psycopg', username='supplypilot_migrator', password=password,
        host='127.0.0.1', port=int(port), database='supplypilot_dev',
    )
    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True,
                           connect_args={'connect_timeout': 10})
    try:
        with engine.connect() as connection:
            with connection.begin():
                database, user = connection.execute(
                    text('SELECT current_database(), current_user')
                ).one()
                if (database, user) != ('supplypilot_dev', 'supplypilot_migrator'):
                    raise RuntimeError('Unexpected migration database or account.')
                context.configure(connection=connection, target_metadata=target_metadata,
                                  version_table_schema='public', compare_type=True)
                with context.begin_transaction():
                    context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError('Offline SQL generation will be configured with the first reviewed migration.')
else:
    run_online()
