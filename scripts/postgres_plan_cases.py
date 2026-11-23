"""Plan snapshot, approval metadata, tenant isolation and rollback acceptance cases."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from uuid import uuid4


def prepare_plan(client,password,check):
    tokens={}
    for role in ('buyer','technical'):
        response=client.post('/api/v1/auth/login',json={'username':role,'password':password})
        check(response.status_code==200,'Pre-upgrade API login succeeds for '+role)
        tokens[role]={'Authorization':'Bearer '+response.json()['access_token']}
    for supplier in ('gulf','desert'):
        response=client.post('/api/v1/offers/offer-'+supplier+'/assess',headers=tokens['technical'],
            json={'expected_revision':1,'certificate_verified':True,'reason':'Synthetic pre-upgrade evidence review'})
        check(response.status_code==200,'Pre-upgrade technical review succeeds for '+supplier)
    response=client.post('/api/v1/plans',headers=tokens['buyer'],
        json={'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000.00'})
    check(response.status_code==201,'Real API sourcing plan exists before plan storage migration')
    return response.json()['id']


def plan_checks(sql,runtime_args,check):
    clone='supplypilot_dev'
    tables=sql(clone,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    def hashes(database):
        return {t:sql(database,'SELECT md5(row_to_json(r)::text) FROM public.'+t+' r ORDER BY 1') for t in tables}
    clone_before=hashes(clone)
    expected="""SELECT tenant,id,revision,data->>'rfq_id',(data->'payload'->>'rfq_revision')::integer,
        data->>'creator',data->>'status',data->>'digest',data::jsonb->'payload',
        (data->'payload'->>'total')::numeric,(data->'payload'->>'budget')::numeric,
        data->'payload'->>'currency',data->'payload'->>'objective',data->>'approved_digest',
        data->>'approver',data->>'reason',(data->>'expires_at')::timestamptz,
        data->>'intent_id',data->>'order_id' FROM records WHERE kind='plan'"""
    check(sql(clone,'WITH expected AS ('+expected+'), actual AS (SELECT * FROM proc_plans) '
        'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
        'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
        'Every existing plan field and complete payload snapshot is preserved')
    check(sql(clone,"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.proc_plans'::regclass")=='t',
          'Plan projection has enabled and forced tenant RLS')
    check(sql(clone,"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.sync_procurement_plan()'::regprocedure")=='supplypilot_migrator',
          'Plan synchronization uses the dedicated migration owner')
    check(sql(clone,"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1',
          'Existing closed AED 7250 order is preserved')
    import psycopg
    from psycopg.types.json import Jsonb
    def digest(payload):
        return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    payload=json.loads(sql(clone,"SELECT data::jsonb->'payload' FROM records WHERE kind='plan' ORDER BY id LIMIT 1"))
    base={'rfq_id':payload['rfq_id'],'payload':payload,'digest':digest(payload),'status':'pending','creator':'buyer'}
    rid='plan-fixture-'+uuid4().hex[:10];foreign_rfq=rid+'-rfq';other=rid+'-other'
    foreign_payload={'rfq_id':foreign_rfq,'rfq_revision':1,'objective':'cost','currency':'AED',
                     'total':'0.00','budget':'0.00','allocations':[],'stock_refs':{},'shortages':{}}
    other_plan={'rfq_id':foreign_rfq,'payload':foreign_payload,'digest':digest(foreign_payload),
                'status':'pending','creator':'other-buyer'}
    with psycopg.connect(**runtime_args,autocommit=True) as conn:
        def tenant(scope='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(scope,))
        def insert(identity,data,scope='demo',kind='plan'):
            conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) "
                "VALUES(%s,%s,%s,1,%s,'2030-01-01','2030-01-01')",(identity,scope,kind,Jsonb(data)))
        def change(data):conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(data),rid))
        def snapshot():
            return tuple(sql(clone,"SELECT md5(row_to_json(r)::text) FROM "+table+" r WHERE id='"+rid+"'")
                         for table in ('records','proc_plans'))
        def expect(action,codes,label):
            rejected=False
            try:
                with conn.transaction():tenant();action();conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except psycopg.Error as error:
                if error.sqlstate not in codes:raise
                rejected=True
            check(rejected,label)
        check(conn.execute('SELECT count(*) FROM proc_plans').fetchone()[0]==0,'No tenant context hides all plans')
        with conn.transaction():tenant();insert(rid,base)
        check(sql(clone,"SELECT status,source_revision,digest FROM proc_plans WHERE id='"+rid+"'")=='pending|1|'+base['digest'],
              'New pending plan synchronizes exact digest and revision')
        check(json.loads(sql(clone,"SELECT payload FROM proc_plans WHERE id='"+rid+"'"))==payload,
              'Complete sourcing payload is preserved without changing its facts')
        approved=dict(deepcopy(base),status='approved',approver='manager',reason='Synthetic manager review',
                      approved_digest=base['digest'],expires_at='2030-01-01T00:00:00+00:00')
        for status in ('approved','rejected','execution_pending','executed','superseded'):
            body=deepcopy(approved);body['status']=status
            if status in ('execution_pending','executed'):body['intent_id']='synthetic-intent-reference'
            if status=='executed':body['order_id']='synthetic-order-reference'
            with conn.transaction():tenant();change(body)
            check(sql(clone,"SELECT status,approved_digest FROM proc_plans WHERE id='"+rid+"'")==status+'|'+base['digest'],
                  status+' plan stores its approval snapshot and link metadata')
        expired=deepcopy(approved);expired['expires_at']='2020-01-01T00:00:00+00:00'
        with conn.transaction():tenant();change(expired)
        check(sql(clone,"SELECT expires_at<'2021-01-01' FROM proc_plans WHERE id='"+rid+"'")=='t',
              'Expired approvals remain readable historical records')
        zero=deepcopy(base);zero['payload'].update(total='0.00',budget='0.00',allocations=[])
        zero['digest']=digest(zero['payload'])
        with conn.transaction():tenant();change(zero)
        check(sql(clone,"SELECT total,budget FROM proc_plans WHERE id='"+rid+"'")=='0.00|0.00',
              'Stock-covered zero-purchase plans remain valid storage records')
        with conn.transaction():tenant();change(approved)
        valid=snapshot()
        invalid=[]
        for field,value in (('status','unknown'),('digest','invalid'),('approved_digest','0'*64),
                            ('approver',None),('approver','buyer'),('expires_at',None),('expires_at','infinity')):
            body=deepcopy(approved);body[field]=value;invalid.append((body,{'23514'},'Invalid '+field+' rejected'))
        for field,value in (('total','-1.00'),('total','0.001'),('budget','0.00'),('total','NaN'),
                            ('currency','USD'),('objective','unknown'),('rfq_revision',1.5),('allocations',{})):
            body=deepcopy(approved);body['payload'][field]=value
            if field=='budget':body['payload']['total']='1.00'
            invalid.append((body,{'23514'},'Invalid payload '+field+' rejected'))
        body=deepcopy(approved);body['payload']['rfq_id']='different-rfq'
        invalid.append((body,{'23514'},'Payload RFQ identity must match the plan header'))
        for status in ('execution_pending','executed'):
            body=deepcopy(approved);body['status']=status
            invalid.append((body,{'23514'},status+' requires its execution link metadata'))
        for body,codes,label in invalid:
            expect(lambda b=body:change(b),codes,label)
            check(snapshot()==valid,'Rejected edit preserves source revision and complete plan projection')
        rfq={'title':'Synthetic other-tenant requirement','due_date':'2030-01-01','status':'draft',
             'owner':'other-buyer','invited':[],'lines':[{'sku':'PLAN-DEMO','quantity':1,'unit':'piece',
             'specs':{'grade':'ASTM A106 Grade B','size':'DN50','schedule':'40','construction':'seamless'}}]}
        with conn.transaction():tenant('other');insert(foreign_rfq,rfq,'other','rfq');insert(other,other_plan,'other')
        for parent in (foreign_rfq,'missing-plan-rfq'):
            body=deepcopy(base);body['rfq_id']=parent;body['payload']['rfq_id']=parent
            body['digest']=digest(body['payload'])
            expect(lambda b=body:change(b),{'23503'},'Unknown or cross-tenant RFQ link is rejected')
        with conn.transaction():
            tenant();check(conn.execute('SELECT count(*) FROM proc_plans WHERE id=%s',(other,)).fetchone()[0]==0,
                           'Demo tenant cannot read the foreign plan')
            check(conn.execute('UPDATE records SET revision=revision+1 WHERE id=%s',(other,)).rowcount==0,
                  'Demo tenant cannot change the foreign source plan')
        with conn.transaction():
            tenant('other');check(conn.execute('SELECT count(*) FROM proc_plans WHERE id=%s',(other,)).fetchone()[0]==1,
                                  'Second tenant sees its own plan')
        check(conn.execute('SELECT count(*) FROM proc_plans').fetchone()[0]==0,'Plan tenant context resets after commit')
        expect(lambda:conn.execute('DELETE FROM proc_plans'),{'42501'},'Plan projection blocks direct runtime writes')
        expect(lambda:conn.execute('SELECT public.sync_procurement_plan()'),{'42501'},'Runtime cannot directly execute the plan synchronization function')
        expect(lambda:conn.execute("UPDATE records SET kind='document' WHERE id=%s",(rid,)),{'23514'},'Plan kind changes are rejected')
        expect(lambda:conn.execute('UPDATE records SET id=%s WHERE id=%s',(rid+'-moved',rid)),{'23514'},'Plan identity changes are rejected')
        try:
            with conn.transaction():
                tenant();change(dict(approved,status='superseded'))
                conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) VALUES(%s,'demo','buyer','plan.rehearsal',%s,'{}','2030-01-01')",(rid+'-audit',rid))
                raise RuntimeError('intentional-plan-rollback')
        except RuntimeError as error:
            if str(error)!='intentional-plan-rollback':raise
        check(snapshot()==valid,'Outer rollback restores source and full plan projection')
        check(sql(clone,"SELECT count(*) FROM audit WHERE id='"+rid+"-audit'")=='0','Outer rollback removes accompanying audit insert')
        with conn.transaction():tenant();conn.execute('DELETE FROM records WHERE id=%s',(rid,))
        check(sql(clone,"SELECT count(*) FROM proc_plans WHERE id='"+rid+"'")=='0','Source deletion cleans the plan projection')
        with conn.transaction():
            tenant('other');conn.execute('DELETE FROM records WHERE id=%s',(other,));conn.execute('DELETE FROM records WHERE id=%s',(foreign_rfq,))
    check(hashes(clone)==clone_before,'Every original table remains unchanged after fixture cleanup')
