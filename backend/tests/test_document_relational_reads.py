from copy import deepcopy
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def document_row():
    return {'id':'doc-test','kind':'document','revision':2,'source_revision':2,
        'created_at':'2026-11-01','updated_at':'2026-11-02','data':{'filename':'legacy.txt'},
        'filename':'projected.txt','sha256':'a'*64,'status':'review_required','error':None,
        'supplier_id':'gulf','parser':'pypdf/text-v1','malware_scanned':False,
        'page_count':3,'stored_page_count':3,'pages':['Unicode — اختبار\nLine two','','Unicode — اختبار\nLine two'],
        'source_snapshot':{'filename':'old.txt','extension':{'note':'kept'},'history':[{'revision':1}]}}


def test_document_metadata_uses_projection_and_keeps_text_private():
    row=document_row();before=deepcopy(row)
    row['source_snapshot']['pages']=['must not leak']
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert result['data']['filename']=='projected.txt'
    assert result['data']['sha256']=='a'*64 and result['data']['malware_scanned'] is False
    assert 'pages' not in result['data'] and 'page_count' not in result['data']
    assert result['data']['history']==[{'revision':1}]
    result['data']['extension']['note']='changed'
    assert row['source_snapshot']['extension']['note']=='kept'
    assert before['pages']==row['pages']


def test_evidence_preserves_page_order_duplicates_whitespace_and_unicode():
    row=document_row();before=deepcopy(row)
    result=relational_reads._document_evidence_view(row,SimpleNamespace(role='buyer'))
    assert result=={'document_id':'doc-test','sha256':'a'*64,'pages':row['pages'],'parser':'pypdf/text-v1'}
    result['pages'][0]='changed'
    assert row==before


@pytest.mark.parametrize('revision',[None,1,3])
def test_missing_or_stale_document_header_fails_closed(revision):
    row=document_row();row['source_revision']=revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503


@pytest.mark.parametrize('count',[0,2,4])
def test_missing_or_extra_page_rows_fail_closed(count):
    row=document_row();row['stored_page_count']=count
    with pytest.raises(HTTPException) as error:
        relational_reads._document_evidence_view(row,SimpleNamespace(role='buyer'))
    assert error.value.detail['code']=='projection_not_ready'


def test_evidence_fails_closed_when_returned_page_array_is_incomplete():
    row=document_row();row['pages']=row['pages'][:1]
    with pytest.raises(HTTPException):
        relational_reads._document_evidence_view(row,SimpleNamespace(role='buyer'))


@pytest.mark.parametrize('snapshot',[None,[],42])
def test_invalid_document_metadata_snapshot_fails_closed(snapshot):
    row=document_row();row['source_snapshot']=snapshot
    with pytest.raises(HTTPException):relational_reads._view(row,SimpleNamespace(role='buyer'))


def test_collection_metadata_does_not_require_loading_page_text():
    row=document_row();row['pages']=None
    assert 'pages' not in relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    query=relational_reads._query('document',SimpleNamespace(role='buyer'))
    assert 'NULL::jsonb AS pages' in query and 'jsonb_agg(p.text_content' not in query


@pytest.mark.parametrize('pages',[[],['Partial text','']])
def test_quarantined_evidence_keeps_existing_read_contract(pages):
    row=document_row();row.update(status='quarantined',pages=pages,page_count=len(pages),stored_page_count=len(pages))
    assert relational_reads._document_evidence_view(row,SimpleNamespace(role='buyer'))['pages']==pages
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))['data']['status']=='quarantined'


@pytest.mark.parametrize('present',[False,True])
def test_optional_error_key_presence_is_preserved(present):
    row=document_row()
    if present:row['source_snapshot']['error']=None
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert ('error' in result) is present


def test_supplier_document_scope_checks_both_source_and_projection():
    query=relational_reads._query('document',SimpleNamespace(role='supplier'),True,include_pages=True)
    assert "r.data->>'supplier_id'=:supplier_id AND h.supplier_id=:supplier_id" in query
    assert 'p.tenant=r.tenant AND p.document_id=r.id' in query


def test_document_keeps_sqlite_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    user=SimpleNamespace(role='buyer')
    assert relational_reads.collection(db,user,'document',0,100) is None
    assert relational_reads.record(db,user,'doc-test') is None
    assert relational_reads.document_evidence(db,user,'doc-test') is None
