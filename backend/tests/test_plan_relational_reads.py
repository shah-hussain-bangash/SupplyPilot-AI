from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def plan_row(status='approved'):
    return {'id':'plan-test','kind':'plan','revision':4,'source_revision':4,
        'created_at':'2026-11-01T00:00:00+00:00','updated_at':'2026-11-02T00:00:00+00:00',
        'data':{'status':'legacy','payload':{'total':'1'},'history':[{'status':'pending'}],
                'extension':{'note':'retained'}},
        'rfq_id':'rfq-test','creator':'buyer','status':status,'digest':'a'*64,
        'payload':{'total':'7250.00','budget':'10000.00','currency':'AED',
                   'allocations':[{'supplier_id':'gulf','unit_price':'120.00','nested':{'note':'kept'}}]},
        'approved_digest':'a'*64,'approver':'manager','reason':'Reviewed exact scenario',
        'expires_at':datetime(2020,1,1,tzinfo=timezone.utc),'intent_id':'intent-test','order_id':'order-test'}


@pytest.mark.parametrize('status',['pending','approved','rejected','superseded','execution_pending','executed'])
def test_plan_reads_projected_snapshot_metadata_and_preserves_history(status):
    row=plan_row(status);before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert result['data']['status']==status
    assert result['data']['payload']==row['payload']
    assert result['data']['creator']=='buyer' and result['data']['approver']=='manager'
    assert result['data']['history']==[{'status':'pending'}]
    assert result['data']['extension']=={'note':'retained'}
    assert result['data']['expires_at']=='2020-01-01T00:00:00+00:00'
    result['data']['payload']['allocations'][0]['nested']['note']='changed'
    assert row==before


@pytest.mark.parametrize('source_revision',[None,3,5])
def test_plan_missing_or_stale_projection_fails_closed(source_revision):
    row=plan_row();row['source_revision']=source_revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503 and error.value.detail['code']=='projection_not_ready'


def test_pending_plan_preserves_absent_approval_and_execution_keys():
    row=plan_row('pending')
    for key in ('approved_digest','approver','reason','expires_at','intent_id','order_id'):row[key]=None
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert not set(('approved_digest','approver','reason','expires_at','intent_id','order_id')) & result['data'].keys()


@pytest.mark.parametrize('value',['2020-01-01T00:00:00.1234+00:00','2020-01-01T00:00:00.00001+00:00'])
def test_plan_collection_and_detail_expiry_formats_match(value):
    row=plan_row();row['expires_at']=value
    page=relational_reads._view(row,SimpleNamespace(role='buyer'))
    row['expires_at']=datetime.fromisoformat(value)
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))==page


def test_plan_keeps_sqlite_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    assert relational_reads.collection(db,SimpleNamespace(role='buyer'),'plan',0,100) is None
    assert relational_reads.record(db,SimpleNamespace(role='buyer'),'plan-test') is None


def test_zero_purchase_snapshot_retains_exact_values():
    row=plan_row();row['payload']={'total':'0.00','budget':'0.00','allocations':[],'stock_refs':{'stock-demo':5}}
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))['data']['payload']==row['payload']
