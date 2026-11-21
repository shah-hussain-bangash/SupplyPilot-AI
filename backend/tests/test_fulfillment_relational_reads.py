from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def ledger_row(kind):
    row={
        'id':'ledger-test', 'kind':kind, 'revision':2, 'source_revision':2,
        'created_at':'2026-11-01T00:00:00+00:00',
        'updated_at':'2026-11-02T00:00:00+00:00',
        'data':{'extension':{'note':'retained'}},
        'order_id':'order-test', 'allocation_index':1, 'expected_revision':5,
        'supplier_id':'desert', 'evidence_id':'evidence-test',
    }
    if kind=='receipt':
        row.update(sku='PIPE-DN50',accepted=20,rejected=3,quarantine=2,
                   at=datetime(2026,11,2,tzinfo=timezone.utc))
        row['data'].update(accepted=1,rejected=0,quarantine=0)
    else:
        row.update(invoice_number='INV-TEST',quantity=25,unit_price='99999999999.99',
                   status='matched',tolerance='exact',match_checks={'price':True},
                   assessment_history=[{'data':{'status':'mismatch','quantity':25}}],
                   rechecked_by='finance',recheck_reason='Receipt now available',
                   rechecked_at=datetime(2026,11,2,tzinfo=timezone.utc))
        row['data'].update(unit_price='1.00',status='mismatch',
                           assessment_history=[],rechecked_by=None,
                           recheck_reason=None,rechecked_at=None)
    return row


def test_receipt_reads_all_dispositions_and_time_from_projection():
    row=ledger_row('receipt'); before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='warehouse'))
    assert [result['data'][k] for k in ('accepted','rejected','quarantine')]==[20,3,2]
    assert result['data']['at']=='2026-11-02T00:00:00+00:00'
    assert result['data']['expected_revision']==5
    assert result['data']['extension']=={'note':'retained'}
    result['data']['extension']['note']='changed'
    assert row==before


def test_invoice_reads_exact_price_and_complete_recheck_assessment_without_aliasing():
    row=ledger_row('invoice'); before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='finance'))
    assert result['data']['unit_price']=='99999999999.99'
    assert result['data']['status']=='matched'
    assert result['data']['rechecked_by']=='finance'
    assert result['data']['rechecked_at']=='2026-11-02T00:00:00+00:00'
    assert result['data']['assessment_history']==row['assessment_history']
    assert result['data']['match_checks']=={'price':True}
    result['data']['assessment_history'][0]['data']['quantity']=0
    result['data']['match_checks']['price']=False
    assert row==before


@pytest.mark.parametrize('kind',['receipt','invoice'])
@pytest.mark.parametrize('source_revision',[None,1,3])
def test_missing_or_stale_ledger_projection_fails_closed(kind,source_revision):
    row=ledger_row(kind); row['source_revision']=source_revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503
    assert error.value.detail['code']=='projection_not_ready'


def test_legacy_invoice_preserves_absent_optional_fields():
    row=ledger_row('invoice'); row['data']={}
    result=relational_reads._view(row,SimpleNamespace(role='finance'))
    for key in ('assessment_history','rechecked_by','recheck_reason','rechecked_at'):
        assert key not in result['data']


def test_invoice_preserves_explicit_null_recheck_fields():
    row=ledger_row('invoice')
    for key in ('rechecked_by','recheck_reason','rechecked_at'):
        row[key]=None
    result=relational_reads._view(row,SimpleNamespace(role='finance'))
    assert all(result['data'][k] is None for k in ('rechecked_by','recheck_reason','rechecked_at'))


@pytest.mark.parametrize('kind',['receipt','invoice'])
def test_ledger_adapter_keeps_sqlite_fallback(kind):
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    assert relational_reads.collection(db,SimpleNamespace(role='buyer'),kind,0,100) is None
    assert relational_reads.record(db,SimpleNamespace(role='buyer'),'ledger-test') is None
