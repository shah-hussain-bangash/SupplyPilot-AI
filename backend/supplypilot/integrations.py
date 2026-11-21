"""Durable local ERP simulator. No live ERP writes are implemented."""
import json
import sqlite3
from datetime import datetime,timezone,date
from copy import deepcopy
from contextlib import contextmanager
from sqlalchemy import select, update
from .config import DATA
from .db import Outbox, Session, User, now, uid, bind_tenant
from .domain import create, get, save, digest, fail, audit, age_seconds
from .planning import money

@contextmanager
def provider_connection():
    db=sqlite3.connect(DATA/'erp-simulator.db',timeout=20)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS orders (key TEXT PRIMARY KEY, digest TEXT NOT NULL, external_id TEXT NOT NULL, payload TEXT NOT NULL)')
        with db:yield db
    finally:
        db.close()

def provider_create(tenant,key,payload,timeout=False):
    key=tenant+':'+key
    with provider_connection() as db:
        db.execute('INSERT OR IGNORE INTO orders VALUES (?,?,?,?)',(key,digest(payload),'SIM-PO-'+uid()[:8],json.dumps(payload)))
        row=db.execute('SELECT digest,external_id FROM orders WHERE key=?',(key,)).fetchone()
        if row[0]!=digest(payload):fail('provider_conflict','Provider key is bound to another payload')
    if timeout:raise TimeoutError('Simulated timeout after durable provider create')
    return row[1]

def provider_lookup(tenant,key):
    with provider_connection() as db:
        row=db.execute('SELECT external_id FROM orders WHERE key=?',(tenant+':'+key,)).fetchone()
    return row[0] if row else None

def intent_view(row):
    return {k:getattr(row,k) for k in ('id','key','plan_id','digest','state','external_id','attempts','created_at')}

def get_intent(db,user,iid):
    row=db.scalar(select(Outbox).where(Outbox.id==iid,Outbox.tenant==user.tenant))
    if not row:fail('not_found','Execution unavailable',404)
    return row

def process(iid,tenant,actor_id,simulate_timeout=False,reconcile_only=False):
    with Session() as db:
        bind_tenant(db,tenant)
        user=db.get(User,actor_id)
        if not user or user.tenant!=tenant:fail('invalid_worker','Invalid worker scope',403)
        row=get_intent(db,user,iid)
        if row.state=='confirmed':return intent_view(row)
        if row.state in ('uncertain','processing') and not reconcile_only:
            fail('reconciliation_required','Uncertain or interrupted execution must be reconciled')
        if reconcile_only:
            external=provider_lookup(tenant,row.key)
            if not external:fail('manual_reconciliation','No provider result found; remain blocked for manual review')
        else:
            p=get(db,user,row.plan_id,'plan');rfq=get(db,user,row.payload['rfq_id'],'rfq')
            approver=db.get(User,p.data.get('approver'))
            if p.data['status']!='execution_pending' or digest(row.payload)!=row.digest or p.data.get('approved_digest')!=row.digest or rfq.revision!=row.payload['rfq_revision']:
                fail('dispatch_precondition','Execution no longer matches approved source revisions')
            if datetime.fromisoformat(p.data['expires_at'])<=datetime.now(timezone.utc):fail('approval_expired','Approval expired before dispatch; cancel pending intent and obtain a new approved plan')
            if not approver or not approver.active or approver.tenant!=tenant or approver.role!='manager' or approver.authority_cents<money(row.payload['total'])*100:fail('approval_authority_changed','Approver authority is no longer valid')
            for sid in row.payload['stock_refs']:
                if age_seconds(get(db,user,sid,'stock').data['as_of'])>3600:fail('stale_inventory','Inventory stale before dispatch; cancel pending intent and refresh')
            if any(a['valid_until']<date.today().isoformat() for a in row.payload['allocations']):fail('expired_offer','Offer expired before dispatch')
            for a in row.payload['allocations']:
                current=get(db,user,a['offer_id'],'offer').data
                if current.get('compliance',{}).get('status')!='compliant' or current.get('compliance_revision')!=rfq.revision:fail('eligibility_changed','Technical evidence is no longer compliant')
                for key in ('specs','recipient','terms','unit_price','currency','delivery_date','valid_until'):
                    if current[key]!=a[key]:fail('offer_changed','Approved offer facts changed before dispatch')
                if get(db,user,a['evidence_id'],'document').data['sha256']!=a['evidence_sha256']:fail('evidence_changed','Approved source changed before dispatch')
            claimed=db.execute(update(Outbox).where(Outbox.id==row.id,Outbox.state=='pending').values(state='processing',attempts=Outbox.attempts+1))
            if claimed.rowcount!=1:fail('already_claimed','Another worker claimed the intent')
            db.commit()
            try:external=provider_create(tenant,row.key,row.payload,simulate_timeout)
            except TimeoutError:
                row=db.get(Outbox,iid);row.state='uncertain';audit(db,user,'execution.uncertain',iid);db.commit()
                return intent_view(row)
        # Lock and CAS aggregate to prevent concurrent reconciliation duplicating local order.
        row=db.scalar(select(Outbox).where(Outbox.id==iid).with_for_update())
        p=get(db,user,row.plan_id,'plan')
        if p.data['status']=='executed':
            row.state='confirmed';row.external_id=external;db.commit();return intent_view(row)
        lines=[dict(a,received=0,accepted=0,rejected=0,quarantine=0) for a in row.payload['allocations']]
        order=create(db,user,'order',{'rfq_id':row.payload['rfq_id'],'plan_id':p.id,'external_id':external,'intent_id':iid,'lines':lines,'status':'confirmed','total':row.payload['total'],'currency':'AED','simulated':True})
        d=deepcopy(p.data);d.update(status='executed',order_id=order.id)
        save(db,user,p,p.revision,d,'execution.confirmed')
        row.state='confirmed';row.external_id=external;audit(db,user,'provider.reconciled',iid,{'external_id':external})
        db.commit();return intent_view(row)
