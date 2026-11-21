from copy import deepcopy
import pytest
from supplypilot.db import Session, Record, User

def setup_case(api,price='120.00'):
    o=api.order()
    r=api.post('/invoices',{'order_id':o['id'],'expected_revision':o['revision'],'allocation_index':0,'invoice_number':'RECHECK-1','quantity':30,'unit_price':price,'evidence_id':'source-demo'},'finance',201)
    return o,r

def receipt(api,o):
    rev=api.get('/record/'+o['id'])['revision']
    api.post('/receipts',{'order_id':o['id'],'expected_revision':rev,'allocation_index':0,'accepted':30,'rejected':0,'quarantine':0,'evidence_id':'source-demo'},'warehouse',201)

def payload(api,o,r):
    return {'expected_revision':r['revision'],'expected_order_revision':api.get('/record/'+o['id'])['revision'],'reason':'Missing receipt recorded and source evidence reviewed'}

def test_same_invoice_history_and_generated_exception_resolution(api):
    o,r=setup_case(api);receipt(api,o)
    updated=api.post('/invoices/'+r['id']+'/recheck',payload(api,o,r),'finance')
    assert updated['id']==r['id'] and updated['revision']==2
    assert updated['data']['status']=='matched'
    for field in ('invoice_number','quantity','unit_price','evidence_id','supplier_id'):
        assert updated['data'][field]==r['data'][field]
    assert updated['data']['assessment_history'][0]['data']['status']=='mismatch'
    assert api.get('/records/invoice')['total']==1
    assert api.get('/records/exception')['items'][0]['data']['status']=='resolved'
    assert any(x['action']=='invoice.rechecked' for x in api.get('/audit','auditor'))
    api.post('/invoices/'+r['id']+'/recheck',payload(api,o,updated),'finance',409)

@pytest.mark.parametrize('price,receive_first,reason',[('121.00',True,'unit_price_mismatch'),('120.00',False,'insufficient_accepted_quantity')])
def test_recheck_never_waives_required_checks(api,price,receive_first,reason):
    o,r=setup_case(api,price)
    if receive_first:receipt(api,o)
    result=api.post('/invoices/'+r['id']+'/recheck',payload(api,o,r),'finance')
    assert result['data']['status']=='mismatch'
    assert result['data']['match_checks']['reasons']==[reason]
    assert api.get('/records/exception')['items'][0]['data']['status']=='open'

def test_cumulative_matching(api):
    o,r=setup_case(api)
    other=api.post('/invoices',{'order_id':o['id'],'expected_revision':api.get('/record/'+o['id'])['revision'],'allocation_index':0,'invoice_number':'OTHER-2','quantity':30,'unit_price':'120.00','evidence_id':'source-demo'},'finance',201)
    receipt(api,o)
    api.post('/invoices/'+r['id']+'/recheck',payload(api,o,r),'finance')
    result=api.post('/invoices/'+other['id']+'/recheck',payload(api,o,other),'finance')
    assert result['data']['status']=='mismatch'
    assert result['data']['match_checks']['previously_matched_quantity']==30

def test_role_and_tenant_scope(api,client,headers):
    o,r=setup_case(api);p=payload(api,o,r)
    for role in ('buyer','warehouse','manager','supplier-gulf'):
        assert client.post('/api/v1/invoices/'+r['id']+'/recheck',json=p,headers=headers(role)).status_code==403
    with Session.begin() as db:db.get(User,'other-buyer').role='finance'
    assert client.post('/api/v1/invoices/'+r['id']+'/recheck',json=p,headers=headers('other-buyer')).status_code==404

def test_stale_revisions(api):
    o,r=setup_case(api);receipt(api,o);p=payload(api,o,r)
    api.post('/invoices/'+r['id']+'/recheck',{**p,'expected_order_revision':1},'finance',409)
    api.post('/invoices/'+r['id']+'/recheck',{**p,'expected_revision':99},'finance',409)
    assert api.get('/record/'+r['id'])['revision']==1

def test_manual_exception_preserved(api):
    o,r=setup_case(api);receipt(api,o)
    with Session.begin() as db:
        case_row=Record(tenant='demo',kind='exception',data={'resource_id':r['id'],'category':'invoice','detail':'Manual accounting investigation remains required','owner':'finance','due_date':'2030-01-01','status':'open'})
        db.add(case_row);db.flush();case={'id':case_row.id}
    api.post('/invoices/'+r['id']+'/recheck',payload(api,o,r),'finance')
    assert api.get('/record/'+case['id'])['data']['status']=='open'

def test_closed_order_cannot_be_rechecked(api):
    o,r=setup_case(api)
    with Session.begin() as db:
        row=db.get(Record,o['id']);d=deepcopy(row.data);d['status']='closed';row.data=d
    api.post('/invoices/'+r['id']+'/recheck',payload(api,o,r),'finance',409)
    assert api.get('/record/'+r['id'])['revision']==1
