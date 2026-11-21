from copy import deepcopy
import httpx
import pytest
from fastapi import HTTPException
from supplypilot.db import Session,Record,User
from supplypilot.domain import save
from supplypilot.model_gateway import validate_sources

def test_cas_blocks_lost_updates(client):
    with Session() as a,Session() as b:
        r1=a.get(Record,'rfq-demo');r2=b.get(Record,'rfq-demo')
        user=a.get(User,'buyer');other=b.get(User,'buyer')
        d=deepcopy(r1.data);d['title']='First writer'
        save(a,user,r1,1,d,'rfq.changed');a.commit()
        d2=deepcopy(r2.data);d2['title']='Lost update'
        with pytest.raises(HTTPException) as e:save(b,other,r2,1,d2,'rfq.changed')
        assert e.value.status_code==409;b.rollback()
    with Session() as db:assert db.get(Record,'rfq-demo').data['title']=='First writer'

def test_model_quote_must_exist():
    r={'model_version':'fixture-v1','candidates':[{'field':'grade','page':1,'quote':'Grade B','suggested_value':'B'}]}
    assert validate_sources(r,['Material Grade B'])['candidates'][0]['start']==9
    with pytest.raises(HTTPException):validate_sources(r,['Material Grade C'])

def test_model_gateway_is_opt_in(api):
    api.post('/documents/source-demo/model-extract',{},status=503)

def test_approved_payload_tampering_blocks_execution(api):
    p=api.ready();api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Reviewed approved payload'},'manager')
    with Session.begin() as db:
        r=db.get(Record,p['id']);d=deepcopy(r.data);d['payload']['allocations'][0]['recipient']='attacker@example.invalid';r.data=d
    r=api.post('/plans/'+p['id']+'/execute',{'expected_revision':2,'key':'tamper-test-0001'},status=409)
    assert r['detail']['code']=='payload_tampered'

def test_no_blind_retry_after_timeout(api):
    p=api.ready();api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Reviewed approved payload'},'manager')
    i=api.post('/plans/'+p['id']+'/execute',{'expected_revision':2,'key':'timeout-test-0001'},status=202)
    assert api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':True})['state']=='uncertain'
    r=api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':False},status=409)
    assert r['detail']['code']=='reconciliation_required'
    assert api.post('/executions/'+i['id']+'/reconcile',{})['state']=='confirmed'

def test_repeat_confirmed_dispatch_does_not_duplicate(api):
    api.order();i=api.get('/executions')[0]
    assert api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':False})['state']=='confirmed'
    assert api.get('/records/order')['total']==1

def test_repeated_invoice_cannot_exceed_accepted_quantity(api):
    o=api.order();a=o['data']['lines'][0]
    api.post('/receipts',{'order_id':o['id'],'allocation_index':0,'expected_revision':1,'accepted':30,'rejected':0,'quarantine':0,'evidence_id':'source-demo'},'warehouse',201)
    body={'order_id':o['id'],'allocation_index':0,'invoice_number':'INV-A','quantity':30,'unit_price':a['unit_price'],'evidence_id':'source-demo'}
    assert api.post('/invoices',{**body,'expected_revision':2},'finance',201)['data']['status']=='matched'
    assert api.post('/invoices',{**body,'invoice_number':'INV-B','expected_revision':3},'finance',201)['data']['status']=='mismatch'

def test_live_mutation_after_execution_requires_amendment(api):
    api.order();r=api.get('/record/rfq-demo')
    result=api.post('/rfqs/rfq-demo/review',{'expected_revision':r['revision'],'lines':r['data']['lines'],'reason':'Change executed quantity'},status=409)
    assert result['detail']['code']=='amendment_required'
