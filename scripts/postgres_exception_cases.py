"""Exception snapshot, tenant links, lifecycle and rollback acceptance checks."""
from copy import deepcopy
import json
from uuid import uuid4


def prepare_exceptions(client,password,check):
    response=client.post('/api/v1/auth/login',json={'username':'buyer','password':password})
    check(response.status_code==200,'Pre-upgrade exception owner login succeeds')
    headers={'Authorization':'Bearer '+response.json()['access_token']}
    response=client.post('/api/v1/documents',headers=headers,files={'file':('exception-demo.txt',b'SYNTHETIC EXCEPTION EVIDENCE ONLY','text/plain')})
    check(response.status_code==201,'Pre-upgrade exception evidence uploads through API')
    doc=response.json()['id']
    body={'resource_id':doc,'category':'manual-demo','detail':'Synthetic exception baseline case',
          'owner':'buyer','due_date':'2030-01-01'}
    response=client.post('/api/v1/exceptions',headers=headers,json=body)
    check(response.status_code==201,'Real API exception exists before storage upgrade')
    case=response.json()
    response=client.post('/api/v1/exceptions/'+case['id']+'/resolve',headers=headers,
        json={'expected_revision':case['revision'],'evidence_id':doc,'reason':'Reviewed synthetic evidence before migration'})
    check(response.status_code==200,'Real API exception resolves before storage upgrade')
    return case['id']


def exception_checks(sql,runtime_args,check):
    clone='supplypilot_dev'
    tables=sql(clone,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    def hashes(database):
        return {t:sql(database,'SELECT md5(row_to_json(r)::text) FROM public.'+t+' r ORDER BY 1') for t in tables}
    clone_before=hashes(clone)
    import psycopg
    from psycopg.types.json import Jsonb
    rid='exception-fixture-'+uuid4().hex[:10]
    parent=rid+'-resource'; doc=rid+'-evidence'; foreign=rid+'-foreign'
    manual_id=rid+'-manual'; automatic_id=rid+'-auto'
    base={'resource_id':parent,'category':'quality','detail':'Synthetic quality investigation',
          'owner':'warehouse','due_date':'2030-01-01','status':'open','extension':{'note':'retained'}}
    manual=dict(base,status='resolved',resolution='Reviewed synthetic evidence',evidence_id=doc,resolved_by='manager')
    automatic=dict(base,category='invoice',status='resolved',resolution_reason='Invoice now matches accepted material',
                   resolution_evidence=doc,resolved_by='finance',resolved_at='2026-11-02T00:00:00.123400+00:00',
                   matched_invoice_revision=2)
    with psycopg.connect(**runtime_args,autocommit=True) as conn:
        def tenant(scope='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(scope,))
        def insert(identity,data,scope='demo',kind='exception'):
            conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) "
                "VALUES(%s,%s,%s,1,%s,'2030-01-01','2030-01-01')",(identity,scope,kind,Jsonb(data)))
        def change(data):conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(data),rid))
        # Pre-existing fixtures prove non-empty backfill for both supported resolution paths.
        with conn.transaction():
            tenant();insert(parent,{},kind='document');insert(doc,{},kind='document')
            insert(rid,base);insert(manual_id,manual);insert(automatic_id,automatic)
        expected="""SELECT tenant,id,revision,data->>'resource_id',data->>'category',data->>'detail',
            data->>'owner',(data->>'due_date')::date,data->>'status',
            data->>'resolution',data->>'evidence_id',data->>'resolution_reason',
            data->>'resolution_evidence',data->>'resolved_by',
            (data->>'resolved_at')::timestamptz,(data->>'matched_invoice_revision')::integer,data::jsonb
            FROM records WHERE kind='exception'"""
        check(sql(clone,'WITH expected AS ('+expected+'), actual AS (SELECT * FROM proc_exceptions) '
            'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
            'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
            'Exception backfill preserves normalized fields and every source snapshot')
        check(sql(clone,"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.proc_exceptions'::regclass")=='t',
              'Exception projection has enabled and forced tenant RLS')
        check(sql(clone,"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.sync_procurement_exception()'::regprocedure")=='supplypilot_migrator',
              'Exception synchronization uses the dedicated migration owner')
        check(sql(clone,"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1',
              'Existing closed AED 7250 order is preserved')
        check(conn.execute('SELECT count(*) FROM proc_exceptions').fetchone()[0]==0,'Missing tenant context hides all exceptions')
        def snapshot():
            return tuple(sql(clone,"SELECT md5(row_to_json(r)::text) FROM "+table+" r WHERE id='"+rid+"'")
                         for table in ('records','proc_exceptions'))
        def expect(action,codes,label):
            rejected=False
            try:
                with conn.transaction():tenant();action();conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except psycopg.Error as error:
                if error.sqlstate not in codes:raise
                rejected=True
            check(rejected,label)
        check(json.loads(sql(clone,"SELECT source_snapshot::text FROM proc_exceptions WHERE id='"+manual_id+"'"))==manual,
              'Manual resolution retains its original field names and complete facts')
        check(json.loads(sql(clone,"SELECT source_snapshot::text FROM proc_exceptions WHERE id='"+automatic_id+"'"))==automatic,
              'Automatic invoice resolution retains matching revision and exact timestamp text')
        with conn.transaction():tenant();change(manual)
        check(sql(clone,"SELECT status,source_revision FROM proc_exceptions WHERE id='"+rid+"'")=='resolved|2',
              'Manual resolve synchronizes status and revision in the source transaction')
        reopened=dict(manual,status='open')
        with conn.transaction():tenant();change(reopened)
        check(json.loads(sql(clone,"SELECT source_snapshot::text FROM proc_exceptions WHERE id='"+rid+"'"))==reopened,
              'Reopening preserves previous resolution facts')
        with conn.transaction():tenant();change(automatic)
        check(sql(clone,"SELECT resolution_evidence,resolution_reason,matched_invoice_revision FROM proc_exceptions WHERE id='"+rid+"'")==doc+'|'+automatic['resolution_reason']+'|2',
              'Invoice auto-resolution synchronizes evidence, reason and matched revision')
        mixed=dict(automatic,resolution='Later manual disposition',evidence_id=doc)
        with conn.transaction():tenant();change(mixed)
        check(json.loads(sql(clone,"SELECT source_snapshot::text FROM proc_exceptions WHERE id='"+rid+"'"))==mixed,
              'Repeated resolution preserves both manual and automatic facts without choosing an alias')
        check(sql(clone,"SELECT resolution,resolution_reason FROM proc_exceptions WHERE id='"+rid+"'")==mixed['resolution']+'|'+automatic['resolution_reason'],
              'Manual and automatic reasons have separate normalized columns')
        with conn.transaction():tenant();change(automatic)
        valid=snapshot()
        invalid=[('status','unknown'),('resource_id',''),('category','x'),('category',23),('detail','x'),
                 ('owner',''),('owner',None),('due_date',None),('due_date','infinity'),
                 ('resolved_at','infinity'),('matched_invoice_revision',0),('matched_invoice_revision',1.5),
                 ('matched_invoice_revision','2'),('resolved_by',None),('resolution_reason','x'),('resolution_evidence',None)]
        for key,value in invalid:
            body=deepcopy(automatic);body[key]=value
            expect(lambda b=body:change(b),{'23514','23502'},'Invalid '+key+' rejected')
            check(snapshot()==valid,'Rejected edit preserves source, revision and full exception projection')
        body=deepcopy(automatic);body['due_date']='2030-02-30'
        expect(lambda:change(body),{'22008','22007'},'Invalid calendar date rejected')
        with conn.transaction():tenant('other');insert(foreign,{},'other','document')
        for key in ('resource_id','resolution_evidence'):
            for identity in (foreign,'missing-exception-parent'):
                body=deepcopy(automatic);body[key]=identity
                expect(lambda b=body:change(b),{'23503'},'Missing or cross-tenant '+key+' link rejected')
                check(snapshot()==valid,'Rejected parent link leaves source and projection unchanged')
        other=rid+'-other'
        with conn.transaction():tenant('other');insert(other,dict(base,resource_id=foreign),'other')
        with conn.transaction():
            tenant();check(conn.execute('SELECT count(*) FROM proc_exceptions WHERE id=%s',(other,)).fetchone()[0]==0,
                           'Demo tenant cannot read the foreign exception')
            check(conn.execute('UPDATE records SET revision=revision+1 WHERE id=%s',(other,)).rowcount==0,
                  'Cross-tenant source update cannot change the foreign exception')
        with conn.transaction():
            tenant('other');check(conn.execute('SELECT count(*) FROM proc_exceptions WHERE id=%s',(other,)).fetchone()[0]==1,
                                  'Second tenant sees its own exception')
        check(conn.execute('SELECT count(*) FROM proc_exceptions').fetchone()[0]==0,'Exception tenant context resets after commit')
        for query in ('DELETE FROM proc_exceptions',"UPDATE proc_exceptions SET status='open'",
                      "INSERT INTO proc_exceptions SELECT * FROM proc_exceptions"):
            expect(lambda q=query:conn.execute(q),{'42501'},'Exception projection blocks direct runtime writes')
        expect(lambda:conn.execute('SELECT public.sync_procurement_exception()'),{'42501'},
               'Runtime cannot directly execute the exception synchronization function')
        expect(lambda:conn.execute("UPDATE records SET kind='document' WHERE id=%s",(rid,)),{'23514'},'Exception kind changes are rejected')
        expect(lambda:conn.execute('UPDATE records SET id=%s WHERE id=%s',(rid+'-moved',rid)),{'23514'},'Exception identity changes are rejected')
        expect(lambda:conn.execute('DELETE FROM records WHERE id=%s',(parent,)),{'23503'},'Referenced resource deletion is rejected')
        expect(lambda:conn.execute('DELETE FROM records WHERE id=%s',(doc,)),{'23503'},'Referenced resolution evidence deletion is rejected')
        try:
            with conn.transaction():
                tenant();change(dict(automatic,status='open'))
                conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) VALUES(%s,'demo','buyer','exception.rehearsal',%s,'{}','2030-01-01')",(rid+'-audit',rid))
                raise RuntimeError('intentional-exception-rollback')
        except RuntimeError as error:
            if str(error)!='intentional-exception-rollback':raise
        check(snapshot()==valid,'Outer rollback restores source and full exception projection')
        check(sql(clone,"SELECT count(*) FROM audit WHERE id='"+rid+"-audit'")=='0','Outer rollback removes accompanying audit insert')
        # A source insert and its referenced resource can be ordered either way in one transaction.
        deferred=rid+'-deferred';later=rid+'-later'
        with conn.transaction():tenant();insert(deferred,dict(base,resource_id=later));insert(later,{},kind='document')
        check(sql(clone,"SELECT resource_id FROM proc_exceptions WHERE id='"+deferred+"'")==later,
              'Deferred resource link supports a balanced source transaction')
        with conn.transaction():
            tenant()
            for identity in (rid,manual_id,automatic_id,deferred,later,parent,doc):conn.execute('DELETE FROM records WHERE id=%s',(identity,))
        check(sql(clone,"SELECT count(*) FROM proc_exceptions WHERE id LIKE '"+rid+"%'")=='1',
              'Source deletion cleans all demo exception projections')
        with conn.transaction():
            tenant('other');conn.execute('DELETE FROM records WHERE id=%s',(other,));conn.execute('DELETE FROM records WHERE id=%s',(foreign,))
    check(hashes(clone)==clone_before,'Every original table remains unchanged after fixture cleanup')
