from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def stock_row():
    return {
        'id':'stock-test','kind':'stock','revision':5,'source_revision':5,
        'created_at':'2026-11-01T00:00:00+00:00','updated_at':'2026-11-02T00:00:00+00:00',
        'data':{'usable':1,'reserved':0,'quarantine':0,'extension':{'note':'retained'},
                'inbound':[{'quantity':1},{'quantity':1}]},
        'sku':'PIPE-DN50','usable':90,'reserved':55,'quarantine':2,
        'source':'local-simulator','as_of':datetime(2026,11,2,tzinfo=timezone.utc),
        'inbound':[{'quantity':20,'confirmed':True,'date':'2026-11-03','reference':{'id':'A'}},
                   {'quantity':7,'confirmed':False,'date':'2026-11-01','reference':{'id':'B'}}],
    }


def test_inventory_uses_normalized_balances_and_ordered_inbound_without_aliasing():
    row=stock_row();before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert [result['data'][k] for k in ('usable','reserved','quarantine')]==[90,55,2]
    assert result['data']['inbound']==row['inbound']
    assert result['data']['extension']=={'note':'retained'}
    assert result['data']['inbound'][1]['confirmed'] is False
    result['data']['inbound'][0]['reference']['id']='changed'
    assert row==before


@pytest.mark.parametrize('present',[False,True])
def test_empty_inventory_preserves_optional_inbound_key(present):
    row=stock_row();row['inbound']=[]
    if present:row['data']['inbound']=[]
    else:row['data'].pop('inbound')
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert ('inbound' in result['data']) is present


@pytest.mark.parametrize('source_revision',[None,4,6])
def test_inventory_missing_or_stale_header_fails_closed(source_revision):
    row=stock_row();row['source_revision']=source_revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503


def test_missing_inbound_rows_fail_closed():
    row=stock_row();row['inbound']=row['inbound'][:1]
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.detail['code']=='projection_not_ready'


@pytest.mark.parametrize('value',[
    '2026-11-02T00:00:00.1234+00:00','2026-11-02T00:00:00.00001+00:00',
    '2026-11-02T00:00:00+00:00','2026-11-02T00:00:00.123456+00:00'])
def test_inventory_collection_and_detail_timestamp_formats_match(value):
    row=stock_row();row['as_of']=value
    collection=relational_reads._view(row,SimpleNamespace(role='buyer'))
    row['as_of']=datetime.fromisoformat(value)
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))==collection


def test_old_inventory_timestamp_can_still_be_read():
    row=stock_row();row['as_of']=datetime(2020,1,1,tzinfo=timezone.utc)
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))['data']['as_of']=='2020-01-01T00:00:00+00:00'


def test_inventory_keeps_sqlite_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    assert relational_reads.collection(db,SimpleNamespace(role='buyer'),'stock',0,100) is None
    assert relational_reads.record(db,SimpleNamespace(role='buyer'),'stock-test') is None
