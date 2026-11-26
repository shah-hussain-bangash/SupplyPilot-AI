from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def quote_row(net='32.00', cost='31.00', contribution='1.00', margin='3.12'):
    snapshot=dict(plan_id='plan-test', net=net, cost=cost, contribution=contribution,
        margin_pct=margin, status='draft_requires_commercial_review', sent=False,
        note='Synthetic only — اختبار', extension={'sequence':[2,1,2]},
        history=[{'note':'original'}])
    return dict(id='quote-test',kind='customer_quote',revision=2,source_revision=2,
        created_at='2026-11-01',updated_at='2026-11-02',data={'legacy':True},
        source_snapshot=snapshot,plan_id='plan-test',net=Decimal(net),cost=Decimal(cost),
        contribution=Decimal(contribution),margin_pct=Decimal(margin),
        status=snapshot['status'],sent=False,note=snapshot['note'])


@pytest.mark.parametrize('amounts',[
    ('32.00','31.00','1.00','3.12'),
    ('1000.00','7250.00','-6250.00','-625.00'),
    ('10000.00','0.00','10000.00','100.00'),
    ('00100.0','000.00','100','100.0')])
def test_exact_projected_financial_snapshot_and_extensions(amounts):
    row=quote_row(*amounts); before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert result==row['source_snapshot']
    result['extension']['sequence'].append(9)
    result['history'][0]['note']='changed'
    assert row==before


def test_metadata_comes_from_projection_without_legacy_fallback():
    row=quote_row(); row.update(plan_id='projected-plan',note='projected note')
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert result['plan_id']=='projected-plan' and result['note']=='projected note'
    assert 'legacy' not in result and 'source_revision' not in result


def test_collection_decimal_text_keeps_fractional_margin_exact():
    row=quote_row('9800.00','7250.00','2550.00','26.02')
    for key in ('net','cost','contribution','margin_pct'):row[key]=str(row[key])
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert result==row['source_snapshot']
    query=relational_reads._query('customer_quote',SimpleNamespace(role='buyer'))
    for key in ('net','cost','contribution','margin_pct'):
        assert f'h.{key}::text AS {key}' in query


@pytest.mark.parametrize('revision',[None,1,3])
def test_missing_or_stale_quote_fails_closed(revision):
    row=quote_row();row['source_revision']=revision
    with pytest.raises(HTTPException) as error:relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503


@pytest.mark.parametrize('snapshot',[None,[],{}, {'net':'NaN'}, {'net':32}])
def test_incomplete_snapshot_fails_closed(snapshot):
    row=quote_row();row['source_snapshot']=snapshot
    with pytest.raises(HTTPException) as error:relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.detail['code']=='projection_not_ready'


@pytest.mark.parametrize('field',['net','cost','contribution','margin_pct'])
def test_amount_disagreement_fails_closed(field):
    row=quote_row();row[field]+=Decimal('0.01')
    with pytest.raises(HTTPException) as error:relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503


def test_supplier_scope_and_tenant_join_do_not_read_source_payload():
    query=relational_reads._query('customer_quote',SimpleNamespace(role='supplier'),True)
    assert 'AND false' in query and 'public.proc_customer_quotes' in query
    assert 'h.tenant=r.tenant AND h.id=r.id' in query
    assert "'{}'::jsonb AS data" in query and 'r.data' not in query


def test_sqlite_retains_aggregate_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    user=SimpleNamespace(role='buyer')
    assert relational_reads.collection(db,user,'customer_quote',0,100) is None
    assert relational_reads.record(db,user,'quote-test') is None
