from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, String, Integer, Text, JSON, UniqueConstraint, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session as OrmSession
from .config import DATABASE_URL

def now():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return str(uuid4())

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(Text, default='')
    tenant: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authority_cents: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[int] = mapped_column(Integer, default=1)

class Record(Base):
    __tablename__ = 'records'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(120))
    resource: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON)
    at: Mapped[str] = mapped_column(String(40), default=now)

class Outbox(Base):
    __tablename__ = 'outbox'
    __table_args__ = (UniqueConstraint('tenant', 'key', name='uq_intent_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(120))
    plan_id: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(30), default='pending')
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=now)

engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False, 'timeout': 20} if DATABASE_URL.startswith('sqlite') else {}, pool_pre_ping=True)
if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def pragmas(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
class TenantSession(OrmSession):
    pass

@event.listens_for(TenantSession, 'after_begin')
def transaction_tenant(session, transaction, connection):
    if connection.dialect.name == 'postgresql':
        connection.execute(text("SELECT set_config('supplypilot.tenant', :tenant, true)"),
                           {'tenant':session.info.get('tenant','')})

def bind_tenant(db, tenant):
    if not isinstance(tenant,str) or not tenant or len(tenant)>64:
        raise ValueError('A valid tenant is required')
    if db.info.get('tenant') not in (None,tenant):
        raise RuntimeError('Tenant switching within a session is forbidden')
    db.info['tenant']=tenant
    if db.in_transaction() and db.get_bind().dialect.name=='postgresql':
        db.connection().execute(text("SELECT set_config('supplypilot.tenant', :tenant, true)"), {'tenant':tenant})

Session = sessionmaker(engine, class_=TenantSession, expire_on_commit=False)

def get_db():
    with Session() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
