import os
from pathlib import Path

DATA = Path(os.getenv('DATA_DIR', './data'))
DATA.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///' + (DATA / 'supplypilot.db').as_posix())
MODE = os.getenv('APP_MODE', 'local')
AUTH_MODE = os.getenv('AUTH_MODE', 'local')
SECRET = os.getenv('TOKEN_SECRET', '')
if not SECRET:
    import secrets
    SECRET = secrets.token_hex(32)
ISSUER = os.getenv('OIDC_ISSUER', '')
AUDIENCE = os.getenv('OIDC_AUDIENCE', '')
JWKS_URL = os.getenv('OIDC_JWKS_URL', '')
if MODE != 'local':
    if AUTH_MODE != 'oidc' or not all([ISSUER, AUDIENCE, JWKS_URL]):
        raise RuntimeError('Non-local mode requires configured OIDC.')
    if DATABASE_URL.startswith('sqlite'):
        raise RuntimeError('Non-local mode requires PostgreSQL.')
MAX_UPLOAD = 5 * 1024 * 1024
