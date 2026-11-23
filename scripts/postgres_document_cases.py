"""Document metadata, ordered page text, tenant links and rollback acceptance cases."""
from copy import deepcopy
import json
from uuid import uuid4


def document_checks(sql,runtime_args,check):
    clone='supplypilot_dev'
    tables=sql(clone,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    def hashes(database):
        return {t:sql(database,'SELECT md5(row_to_json(r)::text) FROM public.'+t+' r ORDER BY 1') for t in tables}
    clone_before=hashes(clone)
    import psycopg
    from psycopg.types.json import Jsonb
    rid='document-fixture-'+uuid4().hex[:10]
    empty=rid+'-empty'; partial=rid+'-partial'; other=rid+'-other'; foreign=rid+'-supplier'
    base={'filename':'synthetic-document.txt','sha256':'a'*64,'status':'review_required',
          'pages':['First page\nPIPE-DN50 — اختبار','', 'First page\nPIPE-DN50 — اختبار'],
          'supplier_id':'gulf','parser':'pypdf/text-v1','malware_scanned':False,
          'extension':{'note':'retained','labels':['demo']}}
    quarantined=dict(base,status='quarantined',pages=[],supplier_id=None,error='Manual review required')
    with psycopg.connect(**runtime_args,autocommit=True) as conn:
        def tenant(scope='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(scope,))
        def insert(identity,data,scope='demo',kind='document'):
            conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) "
                "VALUES(%s,%s,%s,1,%s,'2030-01-01','2030-01-01')",(identity,scope,kind,Jsonb(data)))
        def change(data):conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(data),rid))
        with conn.transaction():
            tenant();insert(rid,base);insert(empty,quarantined)
            insert(partial,dict(quarantined,pages=['Retained partial text','']))
        expected="""SELECT tenant,id,revision,data->>'filename',data->>'sha256',data->>'status',data->>'error',
            data->>'supplier_id',data->>'parser',(data->>'malware_scanned')::boolean,
            jsonb_array_length(data::jsonb->'pages'),data::jsonb-'pages' FROM records WHERE kind='document'"""
        check(sql(clone,'WITH expected AS ('+expected+'), actual AS (SELECT * FROM proc_documents) '
            'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
            'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
            'Document headers and complete metadata snapshots match source records')
        pages="""SELECT r.tenant,r.id,(p.ordinality-1)::integer,p.value FROM records r
            CROSS JOIN LATERAL jsonb_array_elements_text(r.data::jsonb->'pages') WITH ORDINALITY AS p(value,ordinality)
            WHERE r.kind='document'"""
        check(sql(clone,'WITH expected AS ('+pages+'), actual AS (SELECT * FROM proc_document_pages) '
            'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
            'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
            'Parsed page text, duplicates and sequence match every original source')
        check(sql(clone,"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.sync_procurement_document()'::regprocedure")=='supplypilot_migrator',
              'Document synchronization uses the dedicated migration owner')
        for table in ('proc_documents','proc_document_pages'):
            check(sql(clone,"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public."+table+"'::regclass")=='t',table+' has enabled and forced tenant RLS')
            check(conn.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table+' hides data without tenant context')
        check(sql(clone,"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1','Existing closed AED 7250 order is preserved')
        def read_pages(identity):
            return json.loads(sql(clone,"SELECT COALESCE(jsonb_agg(text_content ORDER BY page_index),'[]'::jsonb)::text FROM proc_document_pages WHERE document_id='"+identity+"'"))
        check(read_pages(rid)==base['pages'],'Unicode, newlines, blank pages and duplicate text are preserved exactly')
        check(read_pages(empty)==[],'Empty quarantined document remains representable')
        check(read_pages(partial)==['Retained partial text',''],'Partial parsed pages remain available in quarantined metadata storage')
        check(sql(clone,"SELECT malware_scanned FROM proc_documents WHERE id='"+rid+"'")=='f','Existing unscanned flag remains false')
        changed=deepcopy(base);changed.update(filename='revised.txt',pages=['Second revision','New first page'],error=None)
        with conn.transaction():tenant();change(changed)
        check(sql(clone,"SELECT source_revision,filename,page_count FROM proc_documents WHERE id='"+rid+"'")=='2|revised.txt|2','Metadata and revision synchronize in the source transaction')
        check(read_pages(rid)==changed['pages'],'Replacing pages removes previous text and preserves new sequence')
        with conn.transaction():tenant();change(dict(quarantined,pages=[]))
        check(read_pages(rid)==[] and sql(clone,"SELECT page_count,status FROM proc_documents WHERE id='"+rid+"'")=='0|quarantined','Quarantine with empty pages clears prior parsed text')
        with conn.transaction():tenant();change(changed)
        def snapshot():
            return (sql(clone,"SELECT md5(row_to_json(r)::text) FROM records r WHERE id='"+rid+"'"),
                    sql(clone,"SELECT md5(row_to_json(r)::text) FROM proc_documents r WHERE id='"+rid+"'"),
                    sql(clone,"SELECT md5(row_to_json(r)::text) FROM proc_document_pages r WHERE document_id='"+rid+"' ORDER BY page_index"))
        valid=snapshot()
        def expect(action,codes,label):
            rejected=False
            try:
                with conn.transaction():tenant();action();conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except psycopg.Error as error:
                if error.sqlstate not in codes:raise
                rejected=True
            check(rejected,label)
        invalid=[('filename',''),('filename',None),('sha256','invalid'),('status','approved'),('parser',''),
                 ('malware_scanned','false'),('pages',{}),('pages',[42]),('pages',[None]),('pages',[]),
                 ('pages',[' \t\n']),('pages',['x']*61),('pages',['x'*200001]),('supplier_id',False),('error',False)]
        for key,value in invalid:
            body=deepcopy(changed);body[key]=value
            expect(lambda b=body:change(b),{'23514'},'Invalid '+key+' rejected')
            check(snapshot()==valid,'Rejected edit preserves source, revision, header and all parsed pages')
        supplier={'name':'Synthetic foreign supplier','category':'Industrial pipe','approved':True,'simulated':True}
        with conn.transaction():
            tenant('other');insert(foreign,supplier,'other','supplier');insert(other,dict(base,supplier_id=foreign),'other')
        for supplier_id in (foreign,'missing-document-supplier'):
            body=deepcopy(changed);body['supplier_id']=supplier_id
            expect(lambda b=body:change(b),{'23503'},'Missing or cross-tenant document supplier link rejected')
            check(snapshot()==valid,'Rejected supplier link preserves source and both projections')
        for table in ('proc_documents','proc_document_pages'):
            column='id' if table=='proc_documents' else 'document_id'
            with conn.transaction():
                tenant();check(conn.execute('SELECT count(*) FROM '+table+' WHERE '+column+'=%s',(other,)).fetchone()[0]==0,table+' hides the foreign document')
            with conn.transaction():
                tenant('other');check(conn.execute('SELECT count(*) FROM '+table+' WHERE '+column+'=%s',(other,)).fetchone()[0]>0,table+' exposes its own second-tenant document')
            check(conn.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table+' clears tenant context after commit')
            for query in ('DELETE FROM '+table,'INSERT INTO '+table+' SELECT * FROM '+table):
                expect(lambda q=query:conn.execute(q),{'42501'},table+' blocks direct runtime writes')
        with conn.transaction():
            tenant();check(conn.execute('UPDATE records SET revision=revision+1 WHERE id=%s',(other,)).rowcount==0,'Cross-tenant source update is blocked')
        expect(lambda:conn.execute('SELECT public.sync_procurement_document()'),{'42501'},'Runtime cannot directly execute the document synchronization function')
        expect(lambda:conn.execute("UPDATE records SET kind='job' WHERE id=%s",(rid,)),{'23514'},'Document kind changes are rejected')
        expect(lambda:conn.execute('UPDATE records SET id=%s WHERE id=%s',(rid+'-moved',rid)),{'23514'},'Document identity changes are rejected')
        check(sql(clone,"INSERT INTO proc_document_pages VALUES('demo','missing-document',0,'demo')",True)=='23503','Parsed page requires a parent document')
        check(sql(clone,"INSERT INTO proc_document_pages VALUES('other','"+rid+"',0,'demo')",True)=='23503','Cross-tenant parsed page parent link rejected')
        try:
            with conn.transaction():
                tenant();change(dict(changed,pages=['Rolled back text']))
                conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) VALUES(%s,'demo','buyer','document.rehearsal',%s,'{}','2030-01-01')",(rid+'-audit',rid))
                raise RuntimeError('intentional-document-rollback')
        except RuntimeError as error:
            if str(error)!='intentional-document-rollback':raise
        check(snapshot()==valid,'Outer rollback restores source, header and ordered page text')
        check(sql(clone,"SELECT count(*) FROM audit WHERE id='"+rid+"-audit'")=='0','Outer rollback removes accompanying audit insert')
        with conn.transaction():
            tenant()
            for identity in (rid,empty,partial):conn.execute('DELETE FROM records WHERE id=%s',(identity,))
        check(sql(clone,"SELECT count(*) FROM proc_documents WHERE id IN ('"+rid+"','"+empty+"','"+partial+"')")=='0','Deleting document sources cleans their header projections')
        check(sql(clone,"SELECT count(*) FROM proc_document_pages WHERE document_id='"+rid+"'")=='0','Deleting document source cleans all parsed pages')
        with conn.transaction():tenant('other');conn.execute('DELETE FROM records WHERE id=%s',(other,));conn.execute('DELETE FROM records WHERE id=%s',(foreign,))
    check(hashes(clone)==clone_before,'Every original table remains unchanged after fixture cleanup')
