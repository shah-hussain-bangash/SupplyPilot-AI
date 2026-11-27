"""Completed document-job snapshots, source links, tenant isolation and rollback."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4


def document_job_checks(sql,runtime_args,check):
    clone='supplypilot_dev'
    tables=sql(clone,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    def hashes(database):
        return {t:sql(database,'SELECT md5(row_to_json(r)::text) FROM public.'+t+' r ORDER BY 1') for t in tables}
    clone_before=hashes(clone)
    import psycopg
    from psycopg.types.json import Jsonb
    rid='doc-job-fixture-'+uuid4().hex[:10]
    doc=rid+'-doc'; model_id=rid+'-model'; empty_id=rid+'-empty'
    foreign=rid+'-foreign-doc';other=rid+'-other'
    source_text='SYNTHETIC JOB STORAGE ONLY\nSKU: PIPE-DN50\nUnicode — اختبار'
    document={'filename':'document-job-demo.txt','sha256':hashlib.sha256(source_text.encode('utf-8')).hexdigest(),
              'status':'review_required','pages':[source_text],'supplier_id':None,'parser':'fixture','malware_scanned':False}
    candidate={'field':'sku','raw':'PIPE-DN50','normalized':'PIPE-DN50','page':1,'start':source_text.index('PIPE-DN50'),'end':source_text.index('PIPE-DN50')+len('PIPE-DN50'),'reviewed':False}
    result={'pages':[source_text],'candidates':[candidate],
            'flags':['Human review required'],'extension':{'note':'retained'}}
    base={'document_id':doc,'state':'completed','execution':'synchronous-bounded-graph','result':result,
          'extension':{'tag':'demo'}}
    model_result={'model_version':'synthetic-gateway-contract-only','candidates':[
        {'field':'sku','page':1,'quote':'PIPE-DN50','suggested_value':'PIPE-DN50','start':source_text.index('PIPE-DN50'),'reviewed':False}],
        'human_review_required':True}
    model=dict(base,execution='private-model-gateway',result=model_result)
    empty=deepcopy(base);empty['result']['candidates']=[]
    with psycopg.connect(**runtime_args,autocommit=True) as conn:
        def tenant(scope='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(scope,))
        def insert(identity,data,scope='demo',kind='job'):
            conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) "
                "VALUES(%s,%s,%s,1,%s,'2030-01-01','2030-01-01')",(identity,scope,kind,Jsonb(data)))
        def change(data):conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(data),rid))
        with conn.transaction():
            tenant();insert(doc,document,kind='document');insert(rid,base);insert(model_id,model);insert(empty_id,empty)
        expected="""SELECT tenant,id,revision,data->>'document_id',data->>'state',data->>'execution',
            data::jsonb->'result',jsonb_array_length(data::jsonb->'result'->'candidates'),
            data->'result'->>'model_version',data::jsonb-'result' FROM records WHERE kind='job'"""
        check(sql(clone,'WITH expected AS ('+expected+'), actual AS (SELECT * FROM proc_document_jobs) '
            'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
            'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
            'Every job header, complete result and metadata snapshot matches its source')
        check(sql(clone,"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.proc_document_jobs'::regclass")=='t',
              'Document-job projection has enabled and forced tenant RLS')
        check(sql(clone,"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.sync_procurement_document_job()'::regprocedure")=='supplypilot_migrator',
              'Document-job synchronization uses the dedicated migration owner')
        check(sql(clone,"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1',
              'Existing closed AED 7250 order is preserved')
        check(conn.execute('SELECT count(*) FROM proc_document_jobs').fetchone()[0]==0,'No tenant context hides all document jobs')
        for identity,expected_result in ((rid,result),(model_id,model_result)):
            check(json.loads(sql(clone,"SELECT result::text FROM proc_document_jobs WHERE id='"+identity+"'"))==expected_result,
                  'Complete '+identity.rsplit('-',1)[-1]+' result preserves Unicode, source anchors and human-review facts')
        check(sql(clone,"SELECT model_version,candidate_count FROM proc_document_jobs WHERE id='"+model_id+"'")=='synthetic-gateway-contract-only|1',
              'Synthetic model contract metadata is stored without calling an external model')
        check(sql(clone,"SELECT candidate_count FROM proc_document_jobs WHERE id='"+empty_id+"'")=='0','Empty candidate arrays remain valid completed results')
        revised=deepcopy(base);revised['result']['candidates']=[dict(candidate,raw='DN50'),dict(candidate,raw='second')]
        revised['result']['flags'].append('Synthetic re-evaluation only')
        with conn.transaction():tenant();change(revised)
        check(sql(clone,"SELECT source_revision,candidate_count FROM proc_document_jobs WHERE id='"+rid+"'")=='2|2',
              'Result updates synchronize count and source revision atomically')
        check(json.loads(sql(clone,"SELECT result::text FROM proc_document_jobs WHERE id='"+rid+"'"))==revised['result'],
              'Candidate sequence and nested extensions remain unchanged by storage')
        with conn.transaction():tenant();change(empty)
        check(sql(clone,"SELECT candidate_count FROM proc_document_jobs WHERE id='"+rid+"'")=='0','Replacing results removes prior candidates')
        with conn.transaction():tenant();change(revised)
        def snapshot(identity=rid):
            return tuple(sql(clone,"SELECT md5(row_to_json(r)::text) FROM "+table+" r WHERE id='"+identity+"'")
                         for table in ('records','proc_document_jobs'))
        valid=snapshot()
        def expect(action,codes,label):
            rejected=False
            try:
                with conn.transaction():tenant();action();conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except psycopg.Error as error:
                if error.sqlstate not in codes:raise
                rejected=True
            check(rejected,label)
        for key,value in (('state','pending'),('state',None),('execution','unknown'),('document_id',None),('result',[]),('result',None)):
            body=deepcopy(revised);body[key]=value
            expect(lambda b=body:change(b),{'23514'},'Invalid '+key+' rejected')
            check(snapshot()==valid,'Rejected edit preserves source revision and complete job projection')
        for candidates in ({},[42],[None]):
            body=deepcopy(revised);body['result']['candidates']=candidates
            expect(lambda b=body:change(b),{'23514'},'Invalid candidate structure rejected')
            check(snapshot()==valid,'Rejected candidates preserve all source and projected facts')
        body=deepcopy(revised);body['result'].pop('candidates')
        expect(lambda:change(body),{'23514'},'Missing candidate array rejected')
        model_valid=snapshot(model_id)
        for version in (None,'',42):
            body=deepcopy(model);body['result']['model_version']=version
            expect(lambda b=body:conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(b),model_id)),
                   {'23514'},'Invalid private-model version rejected')
            check(snapshot(model_id)==model_valid,
                  'Private-model version failure leaves its source and projection readable')
        with conn.transaction():tenant('other');insert(foreign,document,'other','document');insert(other,dict(base,document_id=foreign),'other')
        for parent in (foreign,'missing-document-job-parent'):
            expect(lambda p=parent:insert(rid+'-bad-parent',dict(base,document_id=p)),{'23503'},'Missing or cross-tenant source-document link rejected')
        with conn.transaction():
            tenant();check(conn.execute('SELECT count(*) FROM proc_document_jobs WHERE id=%s',(other,)).fetchone()[0]==0,
                           'Demo tenant cannot read another tenant job')
            check(conn.execute('UPDATE records SET revision=revision+1 WHERE id=%s',(other,)).rowcount==0,
                  'Cross-tenant source update is blocked')
        with conn.transaction():
            tenant('other');check(conn.execute('SELECT count(*) FROM proc_document_jobs WHERE id=%s',(other,)).fetchone()[0]==1,
                                  'Second tenant sees its own document job')
        check(conn.execute('SELECT count(*) FROM proc_document_jobs').fetchone()[0]==0,'Document-job tenant context clears after commit')
        for query in ('DELETE FROM proc_document_jobs',"UPDATE proc_document_jobs SET state='completed'",'INSERT INTO proc_document_jobs SELECT * FROM proc_document_jobs'):
            expect(lambda q=query:conn.execute(q),{'42501'},'Document-job projection blocks direct runtime writes')
        expect(lambda:conn.execute('SELECT public.sync_procurement_document_job()'),{'42501'},'Runtime cannot directly execute job synchronization')
        expect(lambda:conn.execute("UPDATE records SET kind='feedback' WHERE id=%s",(rid,)),{'23514'},'Job kind changes are rejected')
        expect(lambda:conn.execute('UPDATE records SET id=%s WHERE id=%s',(rid+'-moved',rid)),{'23514'},'Job identity changes are rejected')
        expect(lambda:change(dict(revised,document_id='source-demo')),{'23514'},'Completed job cannot be reassigned to another document')
        expect(lambda:change(dict(revised,execution='private-model-gateway')),{'23514'},'Completed job execution identity cannot be changed')
        expect(lambda:conn.execute('DELETE FROM records WHERE id=%s',(doc,)),{'23503'},'Source document cannot be deleted while processing jobs reference it')
        try:
            with conn.transaction():
                tenant();change(empty)
                conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) VALUES(%s,'demo','buyer','job.rehearsal',%s,'{}','2030-01-01')",(rid+'-audit',rid))
                raise RuntimeError('intentional-document-job-rollback')
        except RuntimeError as error:
            if str(error)!='intentional-document-job-rollback':raise
        check(snapshot()==valid,'Outer rollback restores source and complete job projection')
        check(sql(clone,"SELECT count(*) FROM audit WHERE id='"+rid+"-audit'")=='0','Outer rollback removes accompanying audit insert')
        later=rid+'-later-doc';deferred=rid+'-deferred'
        with conn.transaction():tenant();insert(deferred,dict(base,document_id=later));insert(later,document,kind='document')
        check(sql(clone,"SELECT document_id FROM proc_document_jobs WHERE id='"+deferred+"'")==later,
              'Deferred parent link supports job and document creation in one transaction')
        with conn.transaction():
            tenant()
            for identity in (rid,model_id,empty_id,deferred,later,doc):conn.execute('DELETE FROM records WHERE id=%s',(identity,))
        check(sql(clone,"SELECT count(*) FROM proc_document_jobs WHERE tenant='demo' AND id LIKE '"+rid+"%'")=='0',
              'Deleting job sources cleans every matching projection')
        with conn.transaction():tenant('other');conn.execute('DELETE FROM records WHERE id=%s',(other,));conn.execute('DELETE FROM records WHERE id=%s',(foreign,))
    check(hashes(clone)==clone_before,'Every original table remains unchanged after fixture cleanup')
