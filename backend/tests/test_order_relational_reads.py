from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def order_row():
    return {
        'id':'order-test', 'kind':'order', 'revision':7, 'source_revision':7,
        'created_at':'2026-11-01T00:00:00+00:00',
        'updated_at':'2026-11-02T00:00:00+00:00',
        'data':{'total':'1.00', 'status':'confirmed', 'lines':[{'quantity':1}],
                'history':[{'status':'confirmed'}], 'extension':{'note':'retained'}},
        'rfq_id':'rfq-test', 'plan_id':'plan-test', 'intent_id':'intent-test',
        'external_id':'SIM-TEST', 'status':'closed', 'total':'99999999999.99',
        'currency':'AED', 'simulated':True,
        'closed_at':datetime(2026,11,2,tzinfo=timezone.utc),
        'lines':[{'supplier_id':'gulf', 'quantity':30, 'unit_price':'120.00',
                  'received':30, 'accepted':30, 'rejected':0, 'quarantine':0,
                  'approved_extension':{'certificate':'snapshot'}}],
    }


def test_order_reads_projected_prices_counters_and_snapshot_without_mutating_source():
    row=order_row(); before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert result['data']['total']=='99999999999.99'
    assert result['data']['lines']==row['lines']
    assert result['data']['history']==row['data']['history']
    assert result['data']['extension']=={'note':'retained'}
    assert result['data']['closed_at']=='2026-11-02T00:00:00+00:00'
    result['data']['lines'][0]['approved_extension']['certificate']='changed'
    assert row==before


@pytest.mark.parametrize('source_revision',[None,6,8])
def test_missing_or_stale_order_header_fails_closed(source_revision):
    row=order_row(); row['source_revision']=source_revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503
    assert error.value.detail['code']=='projection_not_ready'


def test_missing_order_lines_fail_closed():
    row=order_row(); row['lines']=[]
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503


def test_open_order_does_not_add_absent_close_timestamp_or_line_defaults():
    row=order_row(); row['closed_at']=None; row['status']='confirmed'
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert 'closed_at' not in result['data']
    assert 'fixed_freight' not in result['data']['lines'][0]


def test_order_adapter_keeps_sqlite_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    assert relational_reads.collection(db,SimpleNamespace(role='buyer'),'order',0,100) is None
    assert relational_reads.record(db,SimpleNamespace(role='buyer'),'order-test') is None
