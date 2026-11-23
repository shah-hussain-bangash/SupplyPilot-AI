from copy import deepcopy
from datetime import date,datetime,timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def exception_row():
    snapshot={'resource_id':'invoice-test','category':'invoice','detail':'Prior invoice mismatch',
              'owner':'finance','due_date':'2020-01-01','status':'resolved',
              'resolution_reason':'Matched accepted material','resolution_evidence':'source-demo',
              'resolved_by':'finance','resolved_at':'2020-01-01T00:00:00+00:00',
              'matched_invoice_revision':2,'history':[{'status':'open'}],'extension':{'note':'retained'}}
    return {'id':'case-test','kind':'exception','revision':2,'source_revision':2,
            'created_at':'2020-01-01','updated_at':'2020-01-02','data':{'detail':'legacy'},
            'source_snapshot':snapshot,'resource_id':'invoice-test','category':'invoice',
            'detail':'Projected invoice mismatch','owner':'finance','due_date':date(2020,1,1),
            'status':'resolved','resolution':None,'evidence_id':None,
            'resolution_reason':'Matched accepted material','resolution_evidence':'source-demo',
            'resolved_by':'finance','resolved_at':datetime(2020,1,1,tzinfo=timezone.utc),'matched_invoice_revision':2}


def test_exception_consumes_projection_and_full_snapshot_without_aliasing():
    row=exception_row();before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='finance'))
    assert result['data']['detail']=='Projected invoice mismatch'
    assert result['data']['history']==[{'status':'open'}]
    assert result['data']['extension']=={'note':'retained'}
    assert result['data']['matched_invoice_revision']==2
    assert result['data']['due_date']=='2020-01-01'
    result['data']['extension']['note']='changed'
    assert row==before


@pytest.mark.parametrize('revision',[None,1,3])
def test_exception_missing_or_stale_projection_fails_closed(revision):
    row=exception_row();row['source_revision']=revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='finance'))
    assert error.value.status_code==503


@pytest.mark.parametrize('snapshot',[None,[],42])
def test_exception_invalid_snapshot_fails_closed(snapshot):
    row=exception_row();row['source_snapshot']=snapshot
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='finance'))
    assert error.value.detail['code']=='projection_not_ready'


@pytest.mark.parametrize('status',['open','resolved'])
def test_manual_and_automatic_resolution_fields_are_retained_separately(status):
    row=exception_row();row['status']=status
    row['resolution']='Manual investigation completed';row['evidence_id']='manual-doc'
    result=relational_reads._view(row,SimpleNamespace(role='finance'))['data']
    assert result['status']==status
    assert result['resolution']=='Manual investigation completed' and result['evidence_id']=='manual-doc'
    assert result['resolution_reason']=='Matched accepted material' and result['resolution_evidence']=='source-demo'


def test_open_case_preserves_absent_resolution_fields():
    row=exception_row();row['status']='open'
    for key in ('resolution','evidence_id','resolution_reason','resolution_evidence','resolved_by','resolved_at','matched_invoice_revision'):
        row[key]=None;row['source_snapshot'].pop(key,None)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert 'resolution_reason' not in result and 'matched_invoice_revision' not in result


def test_explicit_null_optional_key_is_preserved():
    row=exception_row();row['source_snapshot']['resolution']=None
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))['data']['resolution'] is None


@pytest.mark.parametrize('value',['2020-01-01T00:00:00.1234+00:00','2020-01-01T00:00:00.00001+00:00'])
def test_exception_collection_and_detail_timestamp_formats_match(value):
    row=exception_row();row['resolved_at']=value
    page=relational_reads._view(row,SimpleNamespace(role='finance'))
    row['resolved_at']=datetime.fromisoformat(value)
    assert relational_reads._view(row,SimpleNamespace(role='finance'))==page


def test_exception_keeps_sqlite_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    assert relational_reads.collection(db,SimpleNamespace(role='buyer'),'exception',0,100) is None
    assert relational_reads.record(db,SimpleNamespace(role='buyer'),'case-test') is None
