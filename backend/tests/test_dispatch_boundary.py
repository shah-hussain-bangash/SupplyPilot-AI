from copy import deepcopy
from supplypilot.db import Session,Record

def queued(api):
    p=api.ready();api.post('/plans/'+p['id']+'/decision',{'expected_revision':1,'decision':'approved','reason':'Manager reviewed the frozen payload'},'manager')
    intent=api.post('/plans/'+p['id']+'/execute',{'expected_revision':2,'key':'dispatch-boundary-0001'},status=202)
    return p,intent

def test_expiry_checked_at_dispatch_and_pending_cancel_releases_reservations(api):
    p,i=queued(api)
    with Session.begin() as db:
        r=db.get(Record,p['id']);d=deepcopy(r.data);d['expires_at']='2020-01-01T00:00:00+00:00';r.data=d
    result=api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':False},status=409)
    assert result['detail']['code']=='approval_expired'
    cancelled=api.post('/executions/'+i['id']+'/cancel-pending',{'expected_revision':3})
    assert cancelled['state']=='cancelled'
    assert api.get('/record/stock-demo')['data']['reserved']==10
    assert api.get('/record/offer-gulf')['data']['quantity']==30
    assert api.get('/record/offer-desert')['data']['quantity']==40
    api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':False},status=409)

def test_queued_requirements_and_duplicate_commit_are_locked(api):
    p,i=queued(api);rfq=api.get('/record/rfq-demo')
    api.post('/rfqs/rfq-demo/review',{'expected_revision':1,'lines':rfq['data']['lines'],'reason':'Change before queued dispatch'},status=409)
    api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000.00'},status=409)

def test_revoked_technical_proof_blocks_queued_dispatch(api):
    _,i=queued(api);offer=api.get('/record/offer-gulf')
    api.post('/offers/offer-gulf/assess',{'expected_revision':offer['revision'],'certificate_verified':False,'reason':'Certificate proof was withdrawn'},'technical')
    r=api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':False},status=409)
    assert r['detail']['code']=='eligibility_changed'

def test_cancel_after_possible_external_effect_is_forbidden(api):
    _,i=queued(api)
    api.post('/executions/'+i['id']+'/dispatch',{'simulate_timeout':True})
    r=api.post('/executions/'+i['id']+'/cancel-pending',{'expected_revision':3},status=409)
    assert r['detail']['code']=='reconciliation_required'
