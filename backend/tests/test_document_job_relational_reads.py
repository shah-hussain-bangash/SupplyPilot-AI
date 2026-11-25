from copy import deepcopy
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from supplypilot import relational_reads


def job_row():
    return dict(id='job-test',kind='job',revision=2,source_revision=2,
        created_at='2026-11-01',updated_at='2026-11-02',data={'result':{'legacy':True}},
        document_id='doc-test',state='completed',execution='synchronous-bounded-graph',
        candidate_count=1,model_version=None,
        source_snapshot={'document_id':'old','extension':{'note':'kept'}},
        result={'pages':['Unicode — اختبار\n'], 'candidates':[
            {'field':'sku','raw':'PIPE-DN50','normalized':'PIPE-DN50','page':1,
             'start':0,'end':9,'reviewed':False}],
            'flags':['Human review required'],'extension':{'sequence':[2,1,2]}})


def test_projected_result_preserves_review_facts_and_extensions_without_aliasing():
    row=job_row();before=deepcopy(row)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert result['result']==row['result']
    assert result['document_id']=='doc-test' and result['state']=='completed'
    assert result['result']['candidates'][0]['reviewed'] is False
    assert result['extension']=={'note':'kept'}
    assert 'candidate_count' not in result and 'model_version' not in result['result']
    result['result']['extension']['sequence'].append(7)
    result['extension']['note']='changed'
    assert row==before


def test_private_model_version_comes_from_projection():
    row=job_row();row.update(execution='private-model-gateway',model_version='synthetic-v2')
    row['result'].update(model_version='old',human_review_required=True)
    result=relational_reads._view(row,SimpleNamespace(role='buyer'))['data']
    assert result['result']['model_version']=='synthetic-v2'
    assert result['result']['human_review_required'] is True


def test_empty_candidate_result_is_readable():
    row=job_row();row['result']['candidates']=[];row['candidate_count']=0
    assert relational_reads._view(row,SimpleNamespace(role='buyer'))['data']['result']['candidates']==[]


@pytest.mark.parametrize('revision',[None,1,3])
def test_missing_or_stale_projection_fails_closed(revision):
    row=job_row();row['source_revision']=revision
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.status_code==503


@pytest.mark.parametrize('change',[
    {'source_snapshot':None},{'source_snapshot':[]},{'result':None},
    {'result':[]},{'result':{}},{'result':{'candidates':{}}},
    {'candidate_count':0},{'candidate_count':2}])
def test_incomplete_projected_result_fails_closed(change):
    row=job_row();row.update(change)
    with pytest.raises(HTTPException) as error:
        relational_reads._view(row,SimpleNamespace(role='buyer'))
    assert error.value.detail['code']=='projection_not_ready'


def test_supplier_scope_hides_all_jobs_and_query_avoids_source_result():
    query=relational_reads._query('job',SimpleNamespace(role='supplier'),True)
    assert 'AND false' in query and 'proc_document_jobs' in query
    assert "r.data::jsonb-'result' AS data" in query
    assert 'h.tenant=r.tenant AND h.id=r.id' in query


def test_job_keeps_sqlite_fallback():
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='sqlite')))
    user=SimpleNamespace(role='buyer')
    assert relational_reads.collection(db,user,'job',0,100) is None
    assert relational_reads.record(db,user,'job-test') is None
