"""Immutable review history checks for a disposable PostgreSQL database only."""
from copy import deepcopy
import json
from uuid import uuid4


def prepare_history(client,password,check):
    headers={}
    for role in ('buyer','technical'):
        response=client.post('/api/v1/auth/login',json={'username':role,'password':password})
        check(response.status_code==200,'Pre-upgrade review '+role+' login succeeds')
        headers[role]={'Authorization':'Bearer '+response.json()['access_token']}
    response=client.post('/api/v1/documents',headers=headers['buyer'],files={'file':(
        'history-backfill-demo.txt','📦 SYNTHETIC HISTORY ONLY\nSKU: PIPE-DN50\nQuantity: 30\n'.encode(),'text/plain')})
    check(response.status_code==201,'Pre-upgrade review source upload succeeds')
    doc=response.json()
    job=next(j for j in client.get('/api/v1/records/job',headers=headers['buyer']).json()['items']
             if j['data']['document_id']==doc['id'])
    ids=[]
    for decision in ('accepted','rejected'):
        payload={'expected_job_revision':job['revision'],'expected_document_revision':doc['revision'],
            'source_sha256':doc['data']['sha256'],'candidate_index':1,'decision':decision,
            'reason':'Synthetic historical '+decision+' extraction decision','key':uuid4().hex}
        response=client.post('/api/v1/jobs/'+job['id']+'/field-reviews',headers=headers['technical'],json=payload)
        check(response.status_code==201,'Pre-upgrade '+decision+' event is recorded through the API')
        ids.append(response.json()['id'])
    # Historical events must survive a later metadata revision unchanged.
    from supplypilot.db import Session
    from supplypilot.security import lookup_identity
    from supplypilot.domain import get,save
    with Session.begin() as db:
        user=lookup_identity(db,'technical',by_username=True)
        row=get(db,user,doc['id'],'document')
        save(db,user,row,row.revision,dict(row.data,history_fixture='Later metadata revision'),
             'document.history_fixture')
    return ids


def history_checks(sql,connection_args,check):
    import psycopg
    from psycopg.types.json import Jsonb
    rid=sql('supplypilot_dev',"SELECT id FROM records WHERE kind='evidence_review' AND tenant='demo' ORDER BY id LIMIT 1")
    base=json.loads(sql('supplypilot_dev',"SELECT data::text FROM records WHERE id='"+rid+"'"))
    count=sql('supplypilot_dev','SELECT count(*) FROM proc_evidence_reviews')
    check(sql('supplypilot_dev',"SELECT count(*) FROM proc_evidence_reviews p JOIN records r ON r.tenant=p.tenant AND r.id=p.id WHERE p.source_snapshot=r.data::jsonb AND p.source_revision=r.revision")==count,
          'Every review projection preserves its complete source snapshot and revision')
    check(sql('supplypilot_dev',"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.proc_evidence_reviews'::regclass")=='t',
          'Review history has enabled and forced tenant RLS')
    check(sql('supplypilot_dev',"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.store_evidence_review_event()'::regprocedure")=='supplypilot_migrator',
          'Review history storage uses the dedicated migration owner')
    with psycopg.connect(**connection_args,autocommit=True) as conn:
        def tenant(value='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(value,))
        def insert(identity,data,scope='demo',kind='evidence_review'):
            conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) VALUES(%s,%s,%s,1,%s,'2030-01-01','2030-01-01')",
                         (identity,scope,kind,Jsonb(data)))
        def denied(statement,params,label,codes=('23514',)):
            try:
                with conn.transaction():tenant();conn.execute(statement,params)
            except psycopg.Error as error:check(error.sqlstate in codes,label)
            else:raise AssertionError(label+' unexpectedly succeeded')
        check(conn.execute('SELECT count(*) FROM proc_evidence_reviews').fetchone()[0]==0,
              'Review history is hidden without tenant context')
        check(not conn.execute("SELECT has_table_privilege(current_user,'public.records','TRUNCATE') OR has_table_privilege(current_user,'public.records','TRIGGER')").fetchone()[0],
              'Runtime cannot truncate the source table or install bypass triggers')
        for statement,params,label in (
            ("UPDATE records SET data=jsonb_set(data::jsonb,'{reason}','\"changed history\"'::jsonb) WHERE id=%s",(rid,),'Stored review reason cannot be rewritten'),
            ('UPDATE records SET revision=revision+1 WHERE id=%s',(rid,),'Stored review revision cannot be changed'),
            ("UPDATE records SET kind='feedback' WHERE id=%s",(rid,),'Stored review cannot be converted to another kind'),
            ("UPDATE records SET tenant='other' WHERE id=%s",(rid,),'Stored review tenant cannot be changed'),
            ('UPDATE records SET id=%s WHERE id=%s',('changed-'+uuid4().hex,rid),'Stored review identity cannot be changed'),
            ('DELETE FROM records WHERE id=%s',(rid,),'Stored review event cannot be deleted')):
            denied(statement,params,label)
        for operation in ('INSERT','UPDATE','DELETE'):
            statement={'INSERT':"INSERT INTO proc_evidence_reviews(tenant,id) VALUES('demo','forbidden')",
                       'UPDATE':'UPDATE proc_evidence_reviews SET reason=reason',
                       'DELETE':'DELETE FROM proc_evidence_reviews'}[operation]
            denied(statement,None,'Runtime cannot directly '+operation.lower()+' review projections',('42501',))
        denied('SELECT public.store_evidence_review_event()',None,'Runtime cannot execute review storage directly',('42501',))
        denied('SELECT public.validate_evidence_review_snapshot(%s,1)',(Jsonb(base),),
               'Runtime cannot directly invoke the private snapshot validator',('42501',))
        denied('DELETE FROM records WHERE id=%s',(base['job_id'],),'Referenced extraction cannot be deleted',('23503',))
        denied('DELETE FROM records WHERE id=%s',(base['document_id'],),'Referenced source document cannot be deleted',('23503',))
        fresh=deepcopy(base)
        fresh['document_revision']=int(sql('supplypilot_dev',"SELECT revision FROM records WHERE id='"+base['document_id']+"'"))
        fresh['job_revision']=int(sql('supplypilot_dev',"SELECT revision FROM records WHERE id='"+base['job_id']+"'"))
        for change,label in (({'decision':'approved'},'Unsupported decision'),({'training_use':True},'Training-use expansion'),
            ({'reason':' '},'Blank reason'),({'source_sha256':'0'*64},'Changed source hash'),
            ({'document_revision':999},'Stale source revision'),({'candidate_index':0.5},'Fractional candidate index'),
            ({'document_id':'missing-parent'},'Missing source link'),({'author':'buyer','author_username':'buyer'},'Nontechnical author')):
            data=dict(fresh,request_key=uuid4().hex);data.update(change)
            try:
                with conn.transaction():tenant();insert('bad-review-'+uuid4().hex,data)
            except psycopg.Error as error:check(error.sqlstate in ('23514','23503','22P02'),label+' is rejected without an event')
            else:raise AssertionError(label+' unexpectedly succeeded')
        try:
            with conn.transaction():tenant();insert('duplicate-review-'+uuid4().hex,fresh)
        except psycopg.Error as error:check(error.sqlstate=='23505','Database retry key uniqueness rejects a duplicate review event')
        else:raise AssertionError('Duplicate retry key unexpectedly succeeded')
        class RehearsalRollback(Exception):pass
        convert_id='convert-review-'+uuid4().hex
        try:
            with conn.transaction():
                tenant();insert(convert_id,{'note':'Synthetic non-review fixture'},kind='feedback')
                try:
                    with conn.transaction():
                        conn.execute("UPDATE records SET kind='evidence_review',data=%s WHERE id=%s",(Jsonb(fresh),convert_id))
                except psycopg.Error as error:check(error.sqlstate=='23514','Another record cannot be converted into a review event')
                else:raise AssertionError('Record conversion unexpectedly succeeded')
                raise RehearsalRollback()
        except RehearsalRollback:pass
        identity='rollback-review-'+uuid4().hex
        data=dict(fresh,request_key=uuid4().hex,reason='Synthetic transactional rollback probe')
        try:
            with conn.transaction():
                tenant();insert(identity,data)
                conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) VALUES(%s,'demo','technical','evidence_review.rollback_probe',%s,'{}','2030-01-01')",(identity,identity))
                check(conn.execute('SELECT source_snapshot FROM proc_evidence_reviews WHERE id=%s',(identity,)).fetchone()[0]==data,
                      'New review projection synchronizes atomically inside its source transaction')
                raise RehearsalRollback()
        except RehearsalRollback:pass
        check(sql('supplypilot_dev',"SELECT count(*) FROM records WHERE id='"+identity+"'")=='0' and
              sql('supplypilot_dev',"SELECT count(*) FROM proc_evidence_reviews WHERE id='"+identity+"'")=='0' and
              sql('supplypilot_dev',"SELECT count(*) FROM audit WHERE id='"+identity+"'")=='0',
              'Outer rollback removes the review source, projection and accompanying audit event')
        foreign='review-tenant-'+uuid4().hex[:12]
        sql('supplypilot_dev',"INSERT INTO users(id,username,password_hash,tenant,role,supplier_id,authority_cents,active) "
            "SELECT '"+foreign+"','"+foreign+"',password_hash,'other','technical',NULL,0,1 FROM users WHERE id='technical'")
        try:
            try:
                with conn.transaction():
                    tenant('other')
                    doc_id=foreign+'-doc';job_id=foreign+'-job';review_id=foreign+'-event'
                    text='Quantity: 5'
                    candidate={'field':'quantity','raw':'5','normalized':'5','page':1,'start':10,'end':11,'reviewed':False}
                    insert(doc_id,{'filename':'foreign-review.txt','sha256':'a'*64,'status':'review_required',
                        'error':None,'supplier_id':None,'parser':'synthetic-fixture','malware_scanned':False,'pages':[text]},'other','document')
                    insert(job_id,{'document_id':doc_id,'state':'completed','execution':'synchronous-bounded-graph',
                        'result':{'pages':[text],'candidates':[candidate],'flags':['Human review required']}},'other','job')
                    data=dict(fresh,document_id=doc_id,job_id=job_id,document_revision=1,job_revision=1,
                        source_sha256='a'*64,candidate_index=0,candidate_snapshot=candidate,field='quantity',
                        decision='accepted',reviewed_value='5',author=foreign,author_username=foreign,request_key=uuid4().hex)
                    insert(review_id,data,'other')
                    check(conn.execute('SELECT count(*) FROM proc_evidence_reviews').fetchone()[0]==1,
                          'Second tenant can store and read its own source-bound review')
                    tenant()
                    check(conn.execute('SELECT count(*) FROM proc_evidence_reviews WHERE id=%s',(review_id,)).fetchone()[0]==0,
                          'Demo tenant cannot see the foreign review fixture')
                    check(conn.execute('UPDATE records SET data=data WHERE id=%s',(review_id,)).rowcount==0,
                          'Cross-tenant source update cannot reach the foreign review event')
                    for link in ('document_id','job_id'):
                        changed=dict(fresh,request_key=uuid4().hex);changed[link]=doc_id if link=='document_id' else job_id
                        try:
                            with conn.transaction():insert('cross-review-'+uuid4().hex,changed)
                        except psycopg.Error as error:check(error.sqlstate=='23503','Cross-tenant review '+link+' is rejected')
                        else:raise AssertionError('Cross-tenant review link unexpectedly succeeded')
                    raise RehearsalRollback()
            except RehearsalRollback:pass
            check(sql('supplypilot_dev',"SELECT count(*) FROM records WHERE id LIKE '"+foreign+"-%'")=='0',
                  'Tenant rehearsal rollback removes sources, jobs and immutable event fixtures')
        finally:
            sql('supplypilot_dev',"DELETE FROM users WHERE id='"+foreign+"'")
        with conn.transaction():
            tenant('other')
            check(conn.execute('SELECT count(*) FROM proc_evidence_reviews').fetchone()[0]==0,
                  'Other tenant cannot read demo review history')
        with conn.transaction():
            tenant()
            check(conn.execute('SELECT count(*) FROM proc_evidence_reviews').fetchone()[0]==int(count),
                  'Demo tenant sees its own review history')
        check(conn.execute('SELECT count(*) FROM proc_evidence_reviews').fetchone()[0]==0,
              'Review tenant context clears after commit')
    check(sql('supplypilot_dev','SELECT count(*) FROM proc_evidence_reviews')==count,
          'Rejected edits and rollback leave original review history intact')
    check(sql('supplypilot_dev',"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1',
          'Existing closed AED 7250 order is preserved by review storage checks')


def legacy_failure_checks(docker,container,admin_args,archive,check):
    """Invalid legacy history must stop transactional DDL without data repair."""
    import importlib.util
    from pathlib import Path
    import psycopg
    if not container.startswith('supplypilot-ci-') or not archive.startswith('/tmp/supplypilot-acceptance-'):
        raise ValueError('Negative migration checks require disposable runner resources')
    path=Path(__file__).resolve().parents[1]/'backend/migrations/versions/0014_evidence_review_history.py'
    spec=importlib.util.spec_from_file_location('review_history_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    for fault,code in (('invalid snapshot','23514'),('duplicate retry key','23505')):
        name='supplypilot_review_invalid_'+uuid4().hex
        docker('exec',container,'createdb','-U','postgres',name)
        try:
            docker('exec',container,'pg_restore','-U','postgres','--exit-on-error','--dbname='+name,archive)
            with psycopg.connect(**dict(admin_args,dbname=name),autocommit=True) as db:
                # Only this fresh negative-test clone is returned to its prior schema.
                db.execute('DROP TRIGGER records_evidence_review_immutable ON public.records')
                db.execute('DROP TRIGGER records_evidence_review_store ON public.records')
                db.execute('DROP FUNCTION public.protect_evidence_review_event()')
                db.execute('DROP FUNCTION public.store_evidence_review_event()')
                db.execute('DROP TABLE public.proc_evidence_reviews')
                db.execute('DROP FUNCTION public.validate_evidence_review_snapshot(jsonb,integer)')
                db.execute("UPDATE public.alembic_version SET version_num='0013_proc_customer_quotes'")
                rid=db.execute("SELECT id FROM public.records WHERE kind='evidence_review' ORDER BY id LIMIT 1").fetchone()[0]
                if fault=='invalid snapshot':
                    db.execute("UPDATE public.records SET data=jsonb_set(data::jsonb,'{training_use}','true'::jsonb) WHERE id=%s",(rid,))
                else:
                    db.execute('INSERT INTO public.records(id,tenant,kind,revision,data,created_at,updated_at) '
                        'SELECT %s,tenant,kind,revision,data,created_at,updated_at FROM public.records WHERE id=%s',
                        ('legacy-duplicate-'+uuid4().hex,rid))
                before=db.execute('SELECT md5(row_to_json(r)::text) FROM public.records r ORDER BY 1').fetchall()
                try:
                    with db.transaction():
                        db.execute('SET LOCAL ROLE supplypilot_migrator')
                        db.execute(migration.SQL,prepare=False)
                except psycopg.Error as error:check(error.sqlstate==code,fault+' stops review-history migration explicitly')
                else:raise AssertionError('Invalid legacy history unexpectedly migrated')
                check(db.execute("SELECT to_regclass('public.proc_evidence_reviews'),to_regprocedure('public.store_evidence_review_event()')").fetchone()==(None,None),
                      fault+' rolls back new storage and trigger functions')
                check(db.execute('SELECT md5(row_to_json(r)::text) FROM public.records r ORDER BY 1').fetchall()==before,
                      fault+' failure preserves every original aggregate row without repair')
        finally:
            # The name is generated above and is always a runner-owned clone.
            docker('exec',container,'dropdb','-U','postgres','--force',name)
