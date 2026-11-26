from copy import deepcopy
from uuid import uuid4
import pytest
from supplypilot.db import Session,Record,User


def source(client,headers):
    response=client.post('/api/v1/documents',headers=headers('buyer'),
        files={'file':('field-review.txt','📦 SYNTHETIC ONLY\nSKU: PIPE-DN50\nQuantity: 30\nGrade: ASTM A106 Grade B\n'.encode(),'text/plain')})
    assert response.status_code==201
    doc=response.json()
    jobs=client.get('/api/v1/records/job',headers=headers('buyer')).json()['items']
    return doc,next(j for j in jobs if j['data']['document_id']==doc['id'])


def body(doc,job,**changes):
    return dict(expected_job_revision=job['revision'],expected_document_revision=doc['revision'],
        source_sha256=doc['data']['sha256'],candidate_index=1,decision='accepted',
        reason='Synthetic extracted quantity compared with source text',key=uuid4().hex,**changes)


def post(client,headers,job,payload,role='technical'):
    return client.post('/api/v1/jobs/'+job['id']+'/field-reviews',headers=headers(role),json=payload)


@pytest.mark.parametrize('decision,value',[('accepted','30'),('rejected',None),('corrected','31')])
def test_source_bound_review_event_preserves_extraction_and_business_records(client,headers,decision,value):
    doc,job=source(client,headers)
    before={k:client.get('/api/v1/records/'+k,headers=headers('buyer')).json() for k in ('offer','plan','order','exception')}
    payload=body(doc,job);payload['decision']=decision
    if decision=='corrected':payload['corrected_value']=value
    response=post(client,headers,job,payload);assert response.status_code==201,response.text
    event=response.json();data=event['data']
    assert data['decision']==decision and data['reviewed_value']==value and data['training_use'] is False
    assert data['candidate_snapshot']==job['data']['result']['candidates'][1]
    assert data['author']=='technical' and data['source_sha256']==doc['data']['sha256']
    assert client.get('/api/v1/record/'+job['id'],headers=headers('buyer')).json()==job
    assert client.get('/api/v1/record/'+doc['id'],headers=headers('buyer')).json()==doc
    assert all(client.get('/api/v1/records/'+k,headers=headers('buyer')).json()==v for k,v in before.items())
    audit=client.get('/api/v1/audit',headers=headers('auditor')).json()
    assert len([a for a in audit if a['action']=='evidence_review.recorded' and a['resource']==event['id']])==1


def test_retry_is_idempotent_and_new_key_retains_prior_decision(client,headers):
    doc,job=source(client,headers);payload=body(doc,job)
    first=post(client,headers,job,payload).json()
    before=client.get('/api/v1/audit',headers=headers('auditor')).json()
    assert post(client,headers,job,payload).json()==first
    assert client.get('/api/v1/audit',headers=headers('auditor')).json()==before
    changed=dict(payload,reason='A different decision must use a new request key')
    assert post(client,headers,job,changed).status_code==409
    second=post(client,headers,job,dict(changed,key=uuid4().hex,decision='rejected')).json()
    assert second['id']!=first['id']
    assert client.get('/api/v1/record/'+first['id'],headers=headers('buyer')).json()==first
    assert client.get('/api/v1/records/evidence_review',headers=headers('buyer')).json()['total']==2
    assert client.delete('/api/v1/record/'+first['id'],headers=headers('technical')).status_code==405
    adjudicate=client.post('/api/v1/feedback/'+first['id']+'/adjudicate',headers=headers('technical'),
        json={'expected_revision':1,'decision':'approved','reason':'Wrong record kind cannot be adjudicated'})
    assert adjudicate.status_code==404


@pytest.mark.parametrize('role',['buyer','manager','warehouse','finance','planner','auditor','admin','supplier-gulf','other-buyer'])
def test_only_technical_role_can_record_review(client,headers,role):
    doc,job=source(client,headers)
    assert post(client,headers,job,body(doc,job),role).status_code==403
    assert client.get('/api/v1/records/evidence_review',headers=headers('buyer')).json()['total']==0


def test_supplier_and_cross_tenant_scope(client,headers):
    doc,job=source(client,headers);event=post(client,headers,job,body(doc,job)).json()
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        assert client.get('/api/v1/record/'+event['id'],headers=headers(role)).status_code==404
        assert client.get('/api/v1/records/evidence_review',headers=headers(role)).json()['total']==0
    with Session.begin() as db:
        db.add(User(id='other-reviewer',username='other-reviewer',tenant='other',role='technical',password_hash=''))
    assert post(client,headers,job,body(doc,job),'other-reviewer').status_code==404


@pytest.mark.parametrize('change,status',[
    ({'expected_job_revision':2},409),({'expected_document_revision':2},409),
    ({'source_sha256':'0'*64},409),({'candidate_index':99},422),
    ({'candidate_index':True},422),({'expected_job_revision':True},422),
    ({'decision':'approved'},422),({'reason':'     '},422),
    ({'corrected_value':'31'},422),({'decision':'corrected'},422),
    ({'decision':'corrected','corrected_value':'   '},422)])
def test_invalid_or_stale_review_changes_nothing(client,headers,change,status):
    doc,job=source(client,headers);payload=body(doc,job);payload.update(change)
    assert post(client,headers,job,payload).status_code==status
    assert client.get('/api/v1/records/evidence_review',headers=headers('buyer')).json()['total']==0


@pytest.mark.parametrize('change',['anchor','snapshot','quarantine','missing_result'])
def test_unreliable_source_cannot_be_reviewed(client,headers,change):
    doc,job=source(client,headers)
    with Session.begin() as db:
        if change=='quarantine':
            record=db.get(Record,doc['id']);data=deepcopy(record.data);data['status']='quarantined';record.data=data
        else:
            record=db.get(Record,job['id']);data=deepcopy(record.data)
            if change=='anchor':data['result']['candidates'][1]['start']+=1
            elif change=='snapshot':data['result']['pages']=['Changed processing snapshot']
            else:data['result']=None
            record.data=data
    response=post(client,headers,job,body(doc,job))
    assert response.status_code in (409,422),response.text
    assert client.get('/api/v1/records/evidence_review',headers=headers('buyer')).json()['total']==0


def test_commit_failure_rolls_back_review_and_both_audit_events(client,headers,monkeypatch):
    from sqlalchemy import select,func
    from sqlalchemy.exc import OperationalError
    from supplypilot.db import TenantSession,Audit
    doc,job=source(client,headers)
    def fail_commit(db):raise OperationalError('synthetic failure',None,Exception('test only'))
    with monkeypatch.context() as patch:
        patch.setattr(TenantSession,'commit',fail_commit)
        response=post(client,headers,job,body(doc,job))
    assert response.status_code==503
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Record).where(Record.kind=='evidence_review'))==0
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action.like('evidence_review.%')))==0
    assert client.get('/api/v1/record/'+job['id'],headers=headers('buyer')).json()==job


def test_job_history_pagination_and_scope(client,headers):
    doc,job=source(client,headers)
    events=[post(client,headers,job,body(doc,job)).json() for _ in range(3)]
    path='/api/v1/jobs/'+job['id']+'/field-reviews'
    page=client.get(path+'?limit=2',headers=headers('buyer')).json()
    second=client.get(path+'?offset=2&limit=2',headers=headers('buyer')).json()
    assert page['total']==second['total']==3
    assert {r['id'] for r in page['items']+second['items']}=={r['id'] for r in events}
    for role in ('supplier-gulf','other-buyer'):
        assert client.get(path,headers=headers(role)).status_code==404
    for query in ('?offset=-1','?limit=0','?limit=201'):
        assert client.get(path+query,headers=headers('technical')).status_code==422
