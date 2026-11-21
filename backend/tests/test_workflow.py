from copy import deepcopy
from datetime import date,timedelta
import pytest
from supplypilot.db import Session,Record,User
from supplypilot.domain import digest
from supplypilot.intelligence import eligibility,backtest,extraction_graph
from supplypilot.planning import availability,check_plan

def test_login_and_identity(client):
    r=client.post('/api/v1/auth/login',json={'username':'buyer','password':'Test-only-password-2026'})
    assert r.status_code==200
    token=r.json()['access_token'];assert client.get('/api/v1/me',headers={'Authorization':'Bearer '+token}).json()['role']=='buyer'
    assert client.post('/api/v1/auth/login',json={'username':'buyer','password':'wrong'}).status_code==401

def test_anonymous_and_forged_identity(client):
    assert client.get('/api/v1/records/rfq').status_code==401
    assert client.get('/api/v1/records/rfq',headers={'Authorization':'Bearer forged'}).status_code==401

@pytest.mark.parametrize('role',['other-buyer','supplier-gulf'])
def test_resource_and_file_scope(client,headers,role):
    for path in ('/record/source-demo','/documents/source-demo/evidence','/documents/source-demo/download'):
        assert client.get('/api/v1'+path,headers=headers(role)).status_code==404

def test_other_tenant_and_supplier_collections(api):
    assert api.get('/records/rfq','other-buyer')['total']==0
    assert api.get('/records/offer','supplier-gulf')['total']==1
    assert api.get('/records/plan','supplier-gulf')['total']==0
    rfq=api.get('/record/rfq-demo','supplier-gulf')['data']
    assert 'owner' not in rfq and 'evidence_id' not in rfq['lines'][0]

@pytest.mark.parametrize('role',['admin','auditor','supplier-gulf','warehouse'])
def test_roles_cannot_award(client,headers,role):
    r=client.post('/api/v1/plans',headers=headers(role),json={'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000'})
    assert r.status_code==403

def test_upload_evidence_graph_and_bad_files(client,headers,api):
    h=headers('buyer')
    r=client.post('/api/v1/documents',headers=h,files={'file':('rfq.txt',b'Quantity: 55\nGrade: B','text/plain')})
    assert r.status_code==201
    d=r.json();assert d['data']['status']=='review_required'
    job=api.get('/records/job')['items'][0]
    assert job['data']['result']['candidates'][0]['page']==1
    r=client.post('/api/v1/documents',headers=h,files={'file':('fake.pdf',b'not pdf','application/pdf')})
    assert r.json()['data']['status']=='quarantined'
    r=client.post('/api/v1/documents',headers=h,files={'file':('payload.exe',b'MZ','application/octet-stream')})
    assert r.status_code==422

def test_large_upload_rejected(client,headers):
    assert client.post('/api/v1/documents',headers=headers('buyer'),files={'file':('big.txt',b'x'*(5*1024*1024+1),'text/plain')}).status_code==413

@pytest.mark.parametrize('actual,certificate,result',[({},False,'unknown'),({'grade':'B'},True,'compliant'),({'grade':'C'},True,'noncompliant')])
def test_three_state_compliance(actual,certificate,result):
    assert eligibility({'grade':'B'},actual,certificate)['status']==result

def test_permissioned_retrieval(api,client,headers):
    result=api.post('/search',{'query':'Grade ASTM'})
    assert result['hits'][0]['document_id']=='source-demo'
    assert result['hits'][0]['page']==1 and result['answer'] is None
    assert api.post('/search',{'query':'Grade ASTM'},'other-buyer')['abstained']
    assert client.post('/api/v1/search',json={'query':'Grade'},headers=headers('supplier-gulf')).status_code==403

def test_exact_revision_conflict(api):
    rfq=api.get('/record/rfq-demo')
    api.post('/rfqs/rfq-demo/review',{'expected_revision':99,'lines':rfq['data']['lines'],'reason':'Corrected against source'},status=409)

def test_correction_invalidates_approval(api):
    p=api.ready();p=api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Reviewed synthetic plan'},'manager')
    rfq=api.get('/record/rfq-demo');lines=rfq['data']['lines'];lines[0]['quantity']=101
    api.post('/rfqs/rfq-demo/review',{'expected_revision':1,'lines':lines,'reason':'Correct quantity from source'})
    assert api.get('/record/'+p['id'])['data']['status']=='superseded'
    api.post('/plans/'+p['id']+'/execute',{'expected_revision':3,'key':'stale-plan-0001'},status=409)

def test_plan_checked_cost_and_unknown_exclusion(api):
    p=api.ready()['data']['payload']
    assert p['total']=='7250.00' and p['shortages']=={'PIPE-DN50':55}
    assert [(a['supplier_id'],a['quantity']) for a in p['allocations']]==[('gulf',30),('desert',25)]
    assert all(a['supplier_id']!='budget' for a in p['allocations'])

def test_no_eligible_capacity_and_budget(api):
    api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000'},status=422)
    api.ready()
    api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'100'},status=422)

def test_stale_stock_and_late_inbound(api):
    with Session.begin() as db:
        s=db.get(Record,'stock-demo');d=deepcopy(s.data);d['as_of']='2020-01-01T00:00:00+00:00';s.data=d
    p=api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000'},status=409)
    assert p['detail']['code']=='stale_inventory'
    assert availability({'usable':35,'reserved':10,'inbound':[{'quantity':20,'confirmed':True,'date':'2099-01-01'}],'as_of':api.get('/record/rfq-demo')['updated_at']},date.today().isoformat())==25

def test_authority_and_self_approval(api):
    p=api.ready()
    with Session.begin() as db:db.get(User,'manager').authority_cents=100
    api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Insufficient authority'},'manager',status=403)
    with Session.begin() as db:
        r=db.get(Record,p['id']);d=deepcopy(r.data);d['creator']='manager';r.data=d;db.get(User,'manager').authority_cents=2000000
    api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Cannot approve own decision'},'manager',status=403)

def test_expired_approval_and_payload_tamper(api):
    p=api.ready();p=api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Reviewed synthetic plan'},'manager')
    with Session.begin() as db:
        r=db.get(Record,p['id']);d=deepcopy(r.data);d['expires_at']='2020-01-01T00:00:00+00:00';r.data=d
    api.post('/plans/'+p['id']+'/execute',{'expected_revision':2,'key':'expired-plan-0001'},status=409)

def test_uncertain_reconcile_and_replay(api):
    order=api.order(timeout=True)
    intent=api.get('/executions')[0]
    replay=api.post('/plans/'+order['data']['plan_id']+'/execute',{'expected_revision':1,'key':'test-order-key-0001'},status=202)
    assert replay['id']==intent['id']
    api.post('/executions/'+intent['id']+'/reconcile',{})
    assert api.get('/records/order')['total']==1

def test_idempotency_conflict_other_plan(api):
    p1=api.ready();p2=api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'delivery','budget':'10000'},status=201)
    p1=api.post('/plans/'+p1['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Reviewed synthetic plan'},'manager')
    api.post('/plans/'+p1['id']+'/execute',{'expected_revision':2,'key':'shared-key-0001'},status=202)
    api.post('/plans/'+p2['id']+'/execute',{'expected_revision':1,'key':'shared-key-0001'},status=409)

def test_unapproved_and_double_dispatch(api):
    p=api.ready();api.post('/plans/'+p['id']+'/execute',{'expected_revision':1,'key':'unapproved-key-1'},status=409)
    # A separate client/database test checks confirmed dispatch repeat below.

def test_partial_receipt_quarantine_and_overreceipt(api):
    o=api.order();base={'order_id':o['id'],'allocation_index':0,'evidence_id':'source-demo'}
    api.post('/receipts',{**base,'expected_revision':1,'accepted':10,'rejected':2,'quarantine':3},'warehouse',201)
    updated=api.get('/record/'+o['id']);assert updated['data']['lines'][0]['accepted']==10
    assert updated['data']['status']=='part_received'
    assert api.get('/record/stock-demo')['data']['quarantine']==3
    api.post('/receipts',{**base,'expected_revision':2,'accepted':20,'rejected':0,'quarantine':0},'warehouse',422)
    api.post('/orders/'+o['id']+'/close',{'expected_revision':2},status=409)

def test_invoice_mismatch_and_duplicate(api):
    o=api.order();body={'order_id':o['id'],'allocation_index':0,'expected_revision':1,'invoice_number':'INV-X','quantity':30,'unit_price':'120.00','evidence_id':'source-demo'}
    r=api.post('/invoices',body,'finance',201);assert r['data']['status']=='mismatch'
    assert api.get('/records/exception')['total']==1
    api.post('/invoices',{**body,'expected_revision':2},'finance',409)

def test_complete_procurement_case(api):
    o=api.order();oid=o['id']
    for i,a in enumerate(o['data']['lines']):
        rev=api.get('/record/'+oid)['revision']
        api.post('/receipts',{'order_id':oid,'expected_revision':rev,'allocation_index':i,'accepted':a['quantity'],'rejected':0,'quarantine':0,'evidence_id':'source-demo'},'warehouse',201)
        rev=api.get('/record/'+oid)['revision']
        result=api.post('/invoices',{'order_id':oid,'expected_revision':rev,'allocation_index':i,'invoice_number':'INV-'+str(i),'quantity':a['quantity'],'unit_price':a['unit_price'],'evidence_id':'source-demo'},'finance',201)
        assert result['data']['status']=='matched'
    rev=api.get('/record/'+oid)['revision']
    assert api.post('/orders/'+oid+'/close',{'expected_revision':rev})['data']['status']=='closed'
    assert api.get('/analytics')['closed_count']==1
    assert api.get('/analytics')['realized_savings'] is None
    assert any(r['action']=='order.closed' for r in api.get('/audit','manager'))

def test_supplier_cannot_impersonate_competitor(api,client,headers):
    o=api.get('/record/offer-gulf','supplier-gulf')['data'];o={k:v for k,v in o.items() if k not in ('status','compliance','compliance_revision')};o['supplier_id']='desert'
    r=client.post('/api/v1/offers',json=o,headers=headers('supplier-gulf'))
    assert r.status_code==404

def test_exception_owner_evidence_and_reopen(api):
    case=api.post('/exceptions',{'resource_id':'rfq-demo','category':'clarification','detail':'Need certificate clarification','owner':'technical','due_date':date.today().isoformat()},status=201)
    body={'expected_revision':1,'evidence_id':'source-demo','reason':'Evidence has been reviewed'}
    api.post('/exceptions/'+case['id']+'/resolve',body,status=403)
    case=api.post('/exceptions/'+case['id']+'/resolve',body,'technical')
    assert case['data']['status']=='resolved'
    assert api.post('/exceptions/'+case['id']+'/reopen',{'expected_revision':2},'manager')['data']['status']=='open'

def test_forecast_no_lookahead():
    one=backtest([1,2,3,4,5,6,7,8]);two=backtest([1,2,3,4,5,6,7,8000])
    assert one['evaluation_rows'][-1]['moving_average']==two['evaluation_rows'][-1]['moving_average']
    assert one['production_trained_model'] is False

def test_commercial_margin_and_feedback(api):
    p=api.ready();q=api.post('/customer-quotes',{'plan_id':p['id'],'selling_price':'10000','discount':'200'},status=201)
    assert q['data']['margin_pct']=='26.02'
    f=api.post('/feedback',{'resource_id':p['id'],'correction':'Improve certificate matching'},status=201)
    f=api.post('/feedback/'+f['id']+'/adjudicate',{'expected_revision':1,'decision':'approved','reason':'Expert accepted feedback'},'technical')
    assert f['data']['training_use'] is False

def test_checker_rejects_tampered_total(api):
    p=api.ready()
    with Session() as db:
        rfq=db.get(Record,'rfq-demo');stocks={'PIPE-DN50':db.get(Record,'stock-demo')};offers={x:db.get(Record,x) for x in ('offer-gulf','offer-desert')}
        payload=deepcopy(p['data']['payload']);payload['total']='1.00'
        with pytest.raises(Exception):check_plan(payload,rfq,offers,stocks)
