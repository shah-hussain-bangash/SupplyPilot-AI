"""Source-bound review decisions against disposable PostgreSQL only."""
from uuid import uuid4


def review_workflow(client,check,tokens,race=None):
    def get(path,role='buyer'):
        response=client.get('/api/v1'+path,headers=tokens[role])
        assert response.status_code==200,response.text
        return response.json()
    source='SYNTHETIC FIELD REVIEW ONLY\nSKU: PIPE-DN50\nQuantity: 30\nGrade: ASTM A106 Grade B\n'
    response=client.post('/api/v1/documents',headers=tokens['buyer'],
        files={'file':('field-review-demo.txt',source.encode(),'text/plain')})
    check(response.status_code==201,'Field review source upload succeeds')
    doc=response.json()
    job=next(j for j in get('/records/job')['items'] if j['data']['document_id']==doc['id'])
    path='/jobs/'+job['id']+'/field-reviews'
    payload={'expected_job_revision':job['revision'],'expected_document_revision':doc['revision'],
        'source_sha256':doc['data']['sha256'],'candidate_index':1,'decision':'accepted',
        'reason':'Synthetic quantity checked against its exact source','key':uuid4().hex}
    before={k:get('/records/'+k) for k in ('offer','plan','order','exception')}
    if race:
        outcomes=race(client,tokens,job['id'],path,[payload,payload],'technical',[201,201],
            'Duplicate field review')
        check(outcomes[0].json()==outcomes[1].json(),'Overlapping review retries return the same event')
        event=outcomes[0].json()
    else:
        response=client.post('/api/v1'+path,headers=tokens['technical'],json=payload)
        check(response.status_code==201,'Technical reviewer records a field decision')
        event=response.json()
    check(get(path)['total']==1,'Identical review retries create exactly one history event')
    audit=get('/audit','auditor')
    check(sum(x['action']=='evidence_review.recorded' and x['resource']==event['id'] for x in audit)==1,
        'Review retry creates exactly one recorded audit entry')
    check(sum(x['action']=='evidence_review.created' and x['resource']==event['id'] for x in audit)==1,
        'Review retry creates exactly one creation audit entry')
    check(event['data']['candidate_snapshot']==job['data']['result']['candidates'][1]
          and event['data']['source_sha256']==doc['data']['sha256']
          and event['data']['training_use'] is False,'Review binds exact source facts without training use')
    for decision,value in (('corrected','31'),('rejected',None)):
        body=dict(payload,key=uuid4().hex,decision=decision,reason='Synthetic '+decision+' extraction decision')
        if value is not None:body['corrected_value']=value
        response=client.post('/api/v1'+path,headers=tokens['technical'],json=body)
        check(response.status_code==201 and response.json()['data']['reviewed_value']==value,
            decision+' review stores a separate decision and value')
    first=get(path+'?limit=2');second=get(path+'?limit=2&offset=2')
    check(first['total']==second['total']==3 and len(first['items'])==2 and len(second['items'])==1,
        'Scoped review history retains all decisions across pagination')
    for role in ('buyer','manager','supplier-gulf','other-buyer'):
        response=client.post('/api/v1'+path,headers=tokens[role],json=dict(payload,key=uuid4().hex))
        check(response.status_code==403,role+' cannot write extraction reviews')
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        response=client.get('/api/v1'+path,headers=tokens[role])
        check(response.status_code==404,role+' cannot read internal job review history')
        response=client.get('/api/v1/record/'+event['id'],headers=tokens[role])
        check(response.status_code==404,role+' cannot read another scope review event')
    for change in ({'expected_job_revision':99},{'expected_document_revision':99},{'source_sha256':'0'*64}):
        response=client.post('/api/v1'+path,headers=tokens['technical'],json=dict(payload,key=uuid4().hex,**change))
        check(response.status_code==409,'Stale review binding fails closed: '+next(iter(change)))
    response=client.post('/api/v1'+path,headers=tokens['technical'],json=dict(payload,decision='rejected'))
    check(response.status_code==409 and response.json()['detail']['code']=='idempotency_conflict',
        'Reused review key cannot record a different decision')
    check(get(path)['total']==3,'Rejected field review submissions leave history unchanged')
    check(get('/record/'+job['id'])==job and get('/record/'+doc['id'])==doc,
        'Field reviews preserve complete original extraction and document facts')
    check(all(get('/records/'+k)==v for k,v in before.items()),
        'Extraction reviews do not alter offers, approvals, orders or exceptions')
