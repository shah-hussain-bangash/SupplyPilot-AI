from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from sqlalchemy import select, update
from .db import Outbox, User, Record, now
from .domain import create, get, save, records, expected, evidence, fail, digest, invalidate, audit
from .security import allow
from .intelligence import eligibility
from .planning import generate, check_plan, availability, money

def review_rfq(db,user,rid,body):
    allow(user,'buyer','technical')
    rfq=get(db,user,rid,'rfq');expected(rfq,body.expected_revision)
    if any(o.data['rfq_id']==rid for o in records(db,user,'order')) or any(p.data['rfq_id']==rid and p.data['status']=='execution_pending' for p in records(db,user,'plan')):
        fail('amendment_required','Executed requirements are locked; open an amendment exception')
    lines=[x.model_dump(mode='json') for x in body.lines]
    for line in lines:
        if not line['evidence_id']:fail('evidence_required','Every reviewed line needs source evidence',422)
        evidence(db,user,line['evidence_id'])
    invalidate(db,user,rid,body.reason)
    data=deepcopy(rfq.data);data.update(lines=lines,status='validated',reviewer=user.id,review_reason=body.reason)
    data.setdefault('history',[]).append({'revision':rfq.revision,'lines':rfq.data['lines'],'at':now()})
    return save(db,user,rfq,body.expected_revision,data,'rfq.reviewed')

def invite(db,user,rid,body):
    allow(user,'buyer');rfq=get(db,user,rid,'rfq');expected(rfq,body.expected_revision)
    if rfq.data['status']!='validated':fail('review_required','Review requirements before invitation')
    for sid in body.supplier_ids:get(db,user,sid,'supplier')
    # This action grants portal access only. It does not send email.
    invalidate(db,user,rid,'Supplier invitation changed')
    data=deepcopy(rfq.data);data['invited']=sorted(set(data.get('invited',[])+body.supplier_ids))
    return save(db,user,rfq,rfq.revision,data,'supplier.portal_invited')

def offer(db,user,body):
    allow(user,'buyer','supplier')
    rfq=get(db,user,body.rfq_id,'rfq')
    active=db.scalar(select(Outbox).where(Outbox.tenant==user.tenant,Outbox.state.in_(['pending','processing','uncertain'])))
    if active:
        for intent in db.scalars(select(Outbox).where(Outbox.tenant==user.tenant,Outbox.state.in_(['pending','processing','uncertain']))):
            if intent.payload['rfq_id']==rfq.id:fail('execution_in_progress','Resolve or cancel the pending execution before changing quoted facts')
    if user.role=='supplier' and body.supplier_id!=user.supplier_id:fail('not_found','Supplier unavailable',404)
    if user.role!='supplier':get(db,user,body.supplier_id,'supplier')
    if body.supplier_id not in rfq.data.get('invited',[]):fail('not_invited','Supplier is not invited',403)
    if rfq.data['status']!='validated':fail('review_required','RFQ must be validated')
    if body.sku not in [x['sku'] for x in rfq.data['lines']]:fail('unknown_sku','SKU not in RFQ',422)
    evidence(db,user,body.evidence_id)
    if body.valid_until<date.today():fail('expired_offer','Offer has already expired',422)
    data=body.model_dump(mode='json',exclude={'expected_revision'});data.update(status='submitted',compliance={'status':'unknown'},compliance_revision=None)
    prior=next((o for o in records(db,user,'offer') if o.data['rfq_id']==rfq.id and o.data['supplier_id']==body.supplier_id and o.data['sku']==body.sku),None)
    if prior:
        if body.expected_revision is None:fail('revision_required','Revising a supplier quote requires its current expected_revision')
        expected(prior,body.expected_revision)
        data['history']=prior.data.get('history',[])+[{'revision':prior.revision,'payload':{k:v for k,v in prior.data.items() if k!='history'},'at':now()}]
        invalidate(db,user,rfq.id,'Supplier quotation revised')
        return save(db,user,prior,body.expected_revision,data,'offer.revised')
    return create(db,user,'offer',data)

def assess(db,user,rid,body):
    allow(user,'technical');o=get(db,user,rid,'offer');expected(o,body.expected_revision)
    rfq=get(db,user,o.data['rfq_id'],'rfq');evidence(db,user,o.data['evidence_id'])
    line=next(x for x in rfq.data['lines'] if x['sku']==o.data['sku'])
    result=eligibility(line['specs'],o.data['specs'],body.certificate_verified)
    invalidate(db,user,rfq.id,'Technical assessment changed')
    data=deepcopy(o.data);data.update(compliance=result,compliance_revision=rfq.revision,technical_reviewer=user.id,assessment_reason=body.reason)
    return save(db,user,o,body.expected_revision,data,'offer.assessed')

def plan_inputs(db,user,rfq_id):
    stocks={s.data['sku']:s for s in records(db,user,'stock')}
    approved={s.id for s in records(db,user,'supplier') if s.data.get('approved')}
    offers=[o for o in records(db,user,'offer') if o.data['rfq_id']==rfq_id and o.data['supplier_id'] in approved]
    return stocks,offers

def make_plan(db,user,body):
    allow(user,'buyer','planner');rfq=get(db,user,body.rfq_id,'rfq');expected(rfq,body.expected_revision)
    if rfq.data['status']!='validated':fail('review_required','Review the RFQ first')
    if any(p.data['rfq_id']==rfq.id and p.data['status'] in ('execution_pending','executed') for p in records(db,user,'plan')):fail('already_committed','This requirement has an execution commitment; use the controlled change process')
    stocks,offers=plan_inputs(db,user,rfq.id)
    payload=generate(rfq,stocks,offers,body.objective,body.budget)
    for a in payload['allocations']:
        a['evidence_sha256']=evidence(db,user,a['evidence_id']).data['sha256']
    return create(db,user,'plan',{'rfq_id':rfq.id,'payload':payload,'digest':digest(payload),'status':'pending','creator':user.id})

def fresh(db,user,plan):
    p=plan.data['payload'];rfq=get(db,user,p['rfq_id'],'rfq')
    stocks,offers=plan_inputs(db,user,rfq.id)
    if digest(p)!=plan.data['digest']:fail('payload_tampered','Payload hash mismatch')
    for sid,rev in p['stock_refs'].items():
        if get(db,user,sid,'stock').revision!=rev:fail('stale_inventory','Inventory changed; regenerate plan')
    for a in p['allocations']:
        if evidence(db,user,a['evidence_id']).data['sha256']!=a['evidence_sha256']:fail('evidence_changed','Evidence changed')
    check_plan(p,rfq,{o.id:o for o in offers},stocks)
    return rfq,stocks,offers

def decide(db,user,rid,body):
    allow(user,'manager');p=get(db,user,rid,'plan');expected(p,body.expected_revision)
    if p.data['status']!='pending':fail('invalid_state','Only pending decisions may be approved or rejected')
    if p.data['creator']==user.id:fail('self_approval','Self approval is prohibited',403)
    fresh(db,user,p)
    if money(p.data['payload']['total'])*100>user.authority_cents:fail('authority_limit','Amount exceeds approval authority',403)
    data=deepcopy(p.data);data.update(status=body.decision,approver=user.id,reason=body.reason,approved_digest=p.data['digest'],expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
    return save(db,user,p,body.expected_revision,data,'approval.'+body.decision)

def execute(db,user,rid,body):
    allow(user,'buyer');p=get(db,user,rid,'plan')
    prior=db.scalar(select(Outbox).where(Outbox.tenant==user.tenant,Outbox.key==body.key))
    if prior:
        if prior.plan_id!=rid or prior.digest!=p.data['digest']:fail('idempotency_conflict','Key is already bound to another payload')
        return prior
    expected(p,body.expected_revision)
    if p.data['status']!='approved':fail('not_approved','Current plan has not been approved')
    if p.data['digest']!=p.data['approved_digest'] or datetime.fromisoformat(p.data['expires_at'])<=datetime.now(timezone.utc):fail('approval_expired','Approval expired or differs from payload')
    rfq,stocks,offers=fresh(db,user,p)
    if not p.data['payload']['allocations']:fail('no_purchase','Stock covers this request; no purchase order required',422)
    # Commit internal reservations and consume quoted capacity in the same transaction as intent.
    for line in rfq.data['lines']:
        stock=stocks.get(line['sku'])
        if stock:
            d=deepcopy(stock.data);d['reserved']+=min(line['quantity'],availability(d,rfq.data['due_date']))
            save(db,user,stock,stock.revision,d,'stock.reserved')
    by_id={o.id:o for o in offers}
    for a in p.data['payload']['allocations']:
        o=by_id[a['offer_id']];d=deepcopy(o.data);d['quantity']-=a['quantity']
        save(db,user,o,o.revision,d,'offer.capacity_committed')
    intent=Outbox(tenant=user.tenant,key=body.key,plan_id=p.id,digest=p.data['digest'],payload=deepcopy(p.data['payload']))
    db.add(intent);db.flush()
    data=deepcopy(p.data);data.update(status='execution_pending',intent_id=intent.id)
    save(db,user,p,p.revision,data,'execution.enqueued');audit(db,user,'outbox.created',intent.id,{'key':body.key,'digest':intent.digest})
    return intent

def cancel_pending(db,user,iid,body):
    """Only a never-dispatched intent can be cancelled locally and reservations released."""
    allow(user,'buyer')
    intent=db.scalar(select(Outbox).where(Outbox.id==iid,Outbox.tenant==user.tenant).with_for_update())
    if not intent:fail('not_found','Execution unavailable',404)
    if intent.state!='pending':fail('reconciliation_required','Only never-dispatched pending intent may be cancelled locally')
    p=get(db,user,intent.plan_id,'plan');expected(p,body.expected_revision)
    result=db.execute(update(Outbox).where(Outbox.id==iid,Outbox.state=='pending').values(state='cancelled'))
    if result.rowcount!=1:fail('already_claimed','Dispatch already started; reconcile external state')
    rfq=get(db,user,intent.payload['rfq_id'],'rfq');stocks,offers=plan_inputs(db,user,rfq.id)
    for line in rfq.data['lines']:
        stock=stocks.get(line['sku'])
        if stock:
            d=deepcopy(stock.data);reserved_for_case=line['quantity']-intent.payload['shortages'][line['sku']]
            d['reserved']-=reserved_for_case
            if d['reserved']<0:fail('reservation_invariant','Reservation balance cannot be safely restored')
            save(db,user,stock,stock.revision,d,'stock.pending_reservation_released')
    for a in intent.payload['allocations']:
        o=get(db,user,a['offer_id'],'offer');d=deepcopy(o.data);d['quantity']+=a['quantity']
        save(db,user,o,o.revision,d,'offer.pending_capacity_released')
    d=deepcopy(p.data);d.update(status='superseded',invalidation_reason='Never-dispatched intent cancelled; create and approve a fresh plan')
    save(db,user,p,p.revision,d,'execution.pending_cancelled');audit(db,user,'outbox.cancelled',iid)
    return intent

def receive(db,user,body):
    allow(user,'warehouse');o=get(db,user,body.order_id,'order');expected(o,body.expected_revision)
    if o.data['status']=='closed':fail('closed_order','Closed order requires a controlled correction process')
    evidence(db,user,body.evidence_id)
    lines=o.data['lines']
    if body.allocation_index>=len(lines):fail('invalid_line','Order line unavailable',422)
    a=lines[body.allocation_index];qty=body.accepted+body.rejected+body.quarantine
    if qty<=0 or qty>a['quantity']-a['received']:fail('over_receipt','Receipt exceeds remaining quantity or is empty',422)
    receipt=create(db,user,'receipt',{**body.model_dump(mode='json'),'supplier_id':a['supplier_id'],'sku':a['sku'],'at':now()})
    d=deepcopy(o.data);line=d['lines'][body.allocation_index]
    line['received']+=qty;line['accepted']+=body.accepted;line['rejected']+=body.rejected;line['quarantine']+=body.quarantine
    d['status']='received' if all(x['received']==x['quantity'] for x in d['lines']) else 'part_received'
    save(db,user,o,o.revision,d,'order.receipt_recorded')
    stock=next((x for x in records(db,user,'stock') if x.data['sku']==a['sku']),None)
    if stock:
        sd=deepcopy(stock.data);sd['usable']+=body.accepted;sd['quarantine']+=body.quarantine;sd['as_of']=now()
        save(db,user,stock,stock.revision,sd,'stock.received')
    else:
        create(db,user,'stock',{'sku':a['sku'],'usable':body.accepted,'reserved':0,'quarantine':body.quarantine,'inbound':[],'as_of':now(),'source':'local-simulator'})
    if body.rejected or body.quarantine:
        create(db,user,'exception',{'resource_id':o.id,'category':'quality','detail':'Rejected or quarantined receipt requires disposition','owner':user.id,'due_date':date.today().isoformat(),'status':'open'})
    return receipt

def invoice_checks(db,user,order,index,quantity,unit_price,exclude_id=None):
    if index >= len(order.data['lines']):fail('invalid_line','Order line unavailable',422)
    line=order.data['lines'][index]
    prior=sum(x.data['quantity'] for x in records(db,user,'invoice') if x.id!=exclude_id and x.data['order_id']==order.id and x.data['allocation_index']==index and x.data['status']=='matched')
    remaining=line['accepted']-prior
    reasons=[]
    if quantity>remaining:reasons.append('insufficient_accepted_quantity')
    if money(unit_price)!=money(line['unit_price']):reasons.append('unit_price_mismatch')
    return {'accepted_quantity':line['accepted'],'previously_matched_quantity':prior,
            'remaining_accepted_quantity':remaining,'invoice_quantity':quantity,
            'expected_unit_price':str(line['unit_price']),'invoice_unit_price':str(unit_price),
            'reasons':reasons,'order_revision':order.revision}


def invoice(db,user,body):
    allow(user,'finance');o=get(db,user,body.order_id,'order');expected(o,body.expected_revision)
    if o.data['status']=='closed':fail('closed_order','Closed order requires a controlled correction process')
    evidence(db,user,body.evidence_id)
    checks=invoice_checks(db,user,o,body.allocation_index,body.quantity,body.unit_price)
    a=o.data['lines'][body.allocation_index]
    if any(x.data['supplier_id']==a['supplier_id'] and x.data['invoice_number']==body.invoice_number for x in records(db,user,'invoice')):fail('duplicate_invoice','Supplier invoice number already exists')
    match=not checks['reasons']
    row=create(db,user,'invoice',{**body.model_dump(mode='json'),'supplier_id':a['supplier_id'],'status':'matched' if match else 'mismatch','match_checks':checks,'tolerance':'exact material price and accepted quantity; freight/tax review deferred'})
    save(db,user,o,o.revision,deepcopy(o.data),'order.invoice_reviewed')
    if not match:create(db,user,'exception',{'resource_id':row.id,'category':'invoice','detail':'Three-way matching failed; corrected invoice or controlled resolution required','owner':user.id,'due_date':date.today().isoformat(),'status':'open'})
    return row


def recheck_invoice(db,user,rid,body):
    allow(user,'finance')
    # Determine the parent without locking the invoice, then always lock order first.
    # All invoice creation/recheck paths serialize on the same order row in PostgreSQL.
    lookup=db.scalar(select(Record).where(Record.id==rid,Record.tenant==user.tenant,Record.kind=='invoice'))
    if not lookup:fail('not_found','Resource unavailable',404)
    order=get(db,user,lookup.data['order_id'],'order');expected(order,body.expected_order_revision)
    row=get(db,user,rid,'invoice');expected(row,body.expected_revision)
    if order.data['status']=='closed':fail('closed_order','Closed order requires a controlled correction process')
    if row.data['status']!='mismatch':fail('invalid_state','Only mismatched invoices may be rechecked')
    evidence(db,user,row.data['evidence_id'])
    checks=invoice_checks(db,user,order,row.data['allocation_index'],row.data['quantity'],row.data['unit_price'],exclude_id=row.id)
    line=order.data['lines'][row.data['allocation_index']]
    if line['supplier_id']!=row.data['supplier_id']:fail('invoice_supplier_mismatch','Invoice supplier does not match order line')
    previous=deepcopy(row.data);previous.pop('assessment_history',None)
    data=deepcopy(row.data)
    data['assessment_history']=[*data.get('assessment_history',[]),{'revision':row.revision,'data':previous,'at':now()}]
    data.update(status='mismatch' if checks['reasons'] else 'matched',match_checks=checks,
                rechecked_by=user.id,recheck_reason=body.reason,rechecked_at=now())
    result=save(db,user,row,row.revision,data,'invoice.rechecked')
    save(db,user,order,order.revision,deepcopy(order.data),'order.invoice_rechecked')
    if result.data['status']=='matched':
        for case in records(db,user,'exception'):
            if case.data.get('resource_id')==rid and case.data.get('category')=='invoice' and case.data.get('status')=='open' and case.data.get('detail')=='Three-way matching failed; corrected invoice or controlled resolution required':
                resolved=deepcopy(case.data)
                resolved.update(status='resolved',resolution_evidence=row.data['evidence_id'],
                                resolution_reason=body.reason,resolved_by=user.id,resolved_at=now(),
                                matched_invoice_revision=result.revision)
                save(db,user,case,case.revision,resolved,'exception.invoice_match_resolved')
    return result


def close(db,user,rid,body):
    allow(user,'buyer');o=get(db,user,rid,'order');expected(o,body.expected_revision)
    if o.data['status']=='closed':fail('already_closed','Order is already closed')
    if any(x['accepted']!=x['quantity'] for x in o.data['lines']):fail('open_obligation','Unaccepted quantities or quality obligations remain')
    if any(x.data['status']=='open' and x.data['resource_id']==o.id for x in records(db,user,'exception')):fail('open_exception','Order has an unresolved exception')
    invoices=records(db,user,'invoice')
    for i,a in enumerate(o.data['lines']):
        if sum(x.data['quantity'] for x in invoices if x.data['order_id']==o.id and x.data['allocation_index']==i and x.data['status']=='matched')!=a['quantity']:fail('open_invoice','Accepted material has not been fully matched')
    related={x.id for x in invoices if x.data['order_id']==o.id}
    if any(x.data['status']=='open' and x.data['resource_id'] in related for x in records(db,user,'exception')):fail('open_exception','Invoice exceptions remain')
    d=deepcopy(o.data);d.update(status='closed',closed_at=now())
    return save(db,user,o,o.revision,d,'order.closed')
