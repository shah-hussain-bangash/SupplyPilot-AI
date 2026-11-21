"""Shared transaction boundaries: scoped records, CAS revisions and append-only API audit."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from .db import Record, Audit, now

def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message})

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

def audit(db, user, action, resource, details=None):
    db.add(Audit(tenant=user.tenant, actor=user.id, action=action, resource=resource, details=details or {}))

def create(db, user, kind, data):
    row = Record(tenant=user.tenant, kind=kind, data=deepcopy(data))
    db.add(row); db.flush()
    audit(db, user, kind + '.created', row.id)
    return row

def get(db, user, rid, kind=None):
    row = db.scalar(select(Record).where(Record.id == rid, Record.tenant == user.tenant).with_for_update())
    if not row or (kind and row.kind != kind):
        fail('not_found', 'Resource unavailable', 404)
    if user.role == 'supplier':
        visible = (row.kind == 'offer' and row.data.get('supplier_id') == user.supplier_id) or (row.kind == 'rfq' and user.supplier_id in row.data.get('invited', [])) or (row.kind == 'document' and row.data.get('supplier_id') == user.supplier_id)
        if not visible:
            fail('not_found', 'Resource unavailable', 404)
    return row

def records(db, user, kind):
    rows = list(db.scalars(select(Record).where(Record.tenant == user.tenant, Record.kind == kind).order_by(Record.created_at.desc())))
    if user.role == 'supplier':
        if kind == 'rfq': rows = [r for r in rows if user.supplier_id in r.data.get('invited', [])]
        elif kind in ('offer', 'document'): rows = [r for r in rows if r.data.get('supplier_id') == user.supplier_id]
        else: rows = []
    return rows

def expected(row, revision):
    if row.revision != revision:
        fail('revision_conflict', f'Current revision is {row.revision}')

def save(db, user, row, revision, data, action):
    expected(row, revision)
    result = db.execute(update(Record).where(Record.id == row.id, Record.tenant == user.tenant, Record.revision == revision).values(data=deepcopy(data), revision=revision+1, updated_at=now()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        fail('revision_conflict', 'Concurrent edit; reload before retry')
    db.expire(row); db.refresh(row)
    audit(db, user, action, row.id, {'previous_revision': revision, 'revision': row.revision})
    return row

def view(row, user=None):
    data = deepcopy(row.data)
    if user and user.role == 'supplier' and row.kind == 'rfq':
        data = {k: data[k] for k in ('title', 'due_date', 'lines', 'status') if k in data}
        for line in data.get('lines', []): line.pop('evidence_id', None)
    if row.kind == 'document': data.pop('pages', None)
    return {'id': row.id, 'kind': row.kind, 'revision': row.revision, 'created_at': row.created_at, 'updated_at': row.updated_at, 'data': data}

def age_seconds(value):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()

def evidence(db, user, rid):
    row = get(db, user, rid, 'document')
    if row.data['status'] != 'review_required':
        fail('invalid_evidence', 'Only successfully parsed source documents can support decisions', 422)
    return row

def invalidate(db, user, rfq_id, reason):
    # Internal consequence of an authorized change, including a supplier quote revision.
    # Never return these internal plans to a supplier.
    for p in db.scalars(select(Record).where(Record.tenant==user.tenant,Record.kind=='plan')):
        if p.data['rfq_id'] == rfq_id and p.data['status'] in ('pending', 'approved', 'rejected'):
            d = deepcopy(p.data);d['status'] = 'superseded';d['invalidation_reason'] = reason
            save(db, user, p, p.revision, d, 'plan.superseded')
