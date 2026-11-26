import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, text
from .db import User, get_db, bind_tenant
from . import config

bearer = HTTPBearer(auto_error=False)
jwks = jwt.PyJWKClient(config.JWKS_URL, timeout=5) if config.JWKS_URL else None

def password_hash(password):
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'{salt}:{digest}'

def password_ok(password, stored):
    try:
        salt, expected = stored.split(':')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False

def token_for(user):
    return jwt.encode({'sub': user.id, 'iss': 'supplypilot-local', 'aud': 'supplypilot', 'exp': datetime.now(timezone.utc) + timedelta(minutes=30)}, config.SECRET, algorithm='HS256')

def lookup_identity(db, identity, by_username=False):
    if db.get_bind().dialect.name=='postgresql':
        tenant=db.scalar(text('SELECT public.resolve_identity_tenant(:identity, :by_username)'),
                         {'identity':identity,'by_username':by_username})
        if tenant is None:return None
        bind_tenant(db,tenant)
    query=select(User).where(User.active==1)
    query=query.where(User.username==identity) if by_username else query.where(User.id==identity)
    user=db.scalar(query)
    if user:bind_tenant(db,user.tenant)
    return user


def actor(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db,scope='function')):
    if credentials is None:
        raise HTTPException(401, 'Authentication required')
    try:
        if config.AUTH_MODE == 'oidc':
            key = jwks.get_signing_key_from_jwt(credentials.credentials).key
            claims = jwt.decode(credentials.credentials, key, algorithms=['RS256'], audience=config.AUDIENCE, issuer=config.ISSUER, options={'require': ['exp', 'sub', 'iss', 'aud']})
        else:
            claims = jwt.decode(credentials.credentials, config.SECRET, algorithms=['HS256'], audience='supplypilot', issuer='supplypilot-local', options={'require': ['exp', 'sub']})
        user = lookup_identity(db, claims['sub'])
        if not user or not user.active:
            raise ValueError('Unknown account')
        return user
    except Exception:
        raise HTTPException(401, 'Invalid or expired identity') from None

def allow(user, *roles):
    if user.role not in roles:
        raise HTTPException(403, 'Action not permitted for this account')

def profile(user):
    return {'id': user.id, 'username': user.username, 'tenant': user.tenant, 'role': user.role, 'supplier_id': user.supplier_id, 'authority_cents': user.authority_cents}
