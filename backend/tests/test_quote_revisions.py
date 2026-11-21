def payload(api):
    d=api.get('/record/offer-gulf')['data']
    return {k:v for k,v in d.items() if k not in ('status','compliance','compliance_revision')}

def test_quote_update_requires_revision(api):
    p=payload(api);api.post('/offers',p,status=409)
    p['expected_revision']=99;api.post('/offers',p,status=409)

def test_quote_revision_preserves_history_and_invalidates_plan(api):
    plan=api.ready();p=payload(api)
    p={k:v for k,v in p.items() if k not in ('technical_reviewer','assessment_reason')}
    p.update(expected_revision=2,unit_price='119.00')
    result=api.post('/offers',p,status=201)
    assert result['id']=='offer-gulf' and result['revision']==3
    assert result['data']['compliance']['status']=='unknown'
    assert result['data']['history'][0]['revision']==2
    assert api.get('/record/'+plan['id'])['data']['status']=='superseded'

def test_duplicate_active_exception_returns_existing(api):
    from datetime import date
    p={'resource_id':'rfq-demo','category':'missing-proof','detail':'Need proof of mandatory certificate','owner':'technical','due_date':date.today().isoformat()}
    one=api.post('/exceptions',p,status=201);two=api.post('/exceptions',p,status=201)
    assert one['id']==two['id']
