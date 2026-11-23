"""Inventory backfill, synchronization, isolation and rollback acceptance cases."""
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4


def inventory_checks(sql,runtime_args,check):
    clone='supplypilot_dev'
    tables=sql(clone,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    def hashes(database):
        return {t:sql(database,'SELECT md5(row_to_json(r)::text) FROM public.'+t+' r ORDER BY 1') for t in tables}
    clone_before=hashes(clone)
    expected="""SELECT tenant,id,revision,data->>'sku',(data->>'usable')::integer,
        (data->>'reserved')::integer,(data->>'quarantine')::integer,
        (data->>'as_of')::timestamptz,data->>'source' FROM records WHERE kind='stock'"""
    expected_lines="""SELECT r.tenant,r.id,(x.n-1)::integer,(x.v->>'quantity')::integer,
        (x.v->>'confirmed')::boolean,(x.v->>'date')::date,x.v
        FROM records r CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.data::jsonb->'inbound','[]'::jsonb))
        WITH ORDINALITY x(v,n) WHERE r.kind='stock'"""
    for table,query in (('proc_stock',expected),('proc_stock_inbound',expected_lines)):
        check(sql(clone,'WITH expected AS ('+query+'), actual AS (SELECT * FROM '+table+') '
            'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
            'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
            table+' backfill preserves all original fields and sequence')
        check(sql(clone,"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public."+table+"'::regclass")=='t',
              table+' has enabled and forced tenant RLS')
    check(sql(clone,"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.sync_procurement_stock()'::regprocedure")=='supplypilot_migrator',
          'Inventory synchronization uses the dedicated migration owner')
    check(sql(clone,"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1',
          'Existing closed AED 7250 order is preserved')
    import psycopg
    from psycopg.types.json import Jsonb
    rid='inventory-fixture-'+uuid4().hex[:10];other=rid+'-other'
    payload={'sku':'INVENTORY-DEMO','usable':10,'reserved':5,'quarantine':2,
        'as_of':datetime.now(timezone.utc).isoformat(),'source':'synthetic-inventory-rehearsal',
        'inbound':[{'quantity':20,'confirmed':True,'date':'2030-02-01','reference':'mock-A'},
                   {'quantity':7,'confirmed':False,'date':'2030-01-15','reference':'mock-B'}]}
    with psycopg.connect(**runtime_args,autocommit=True) as conn:
        def tenant(scope='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(scope,))
        def insert(identity,data,scope='demo'):
            conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) "
                "VALUES(%s,%s,'stock',1,%s,'2030-01-01','2030-01-01')",(identity,scope,Jsonb(data)))
        def change(data):conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(data),rid))
        def snapshot():
            return tuple(sql(clone,"SELECT md5(row_to_json(r)::text) FROM "+table+" r WHERE "+column+"='"+rid+"' ORDER BY 1")
                         for table,column in (('records','id'),('proc_stock','id'),('proc_stock_inbound','stock_id')))
        def expect(action,codes,label):
            rejected=False
            try:
                with conn.transaction():
                    tenant();action();conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except psycopg.Error as error:
                if error.sqlstate not in codes:raise
                rejected=True
            check(rejected,label)
        for table in ('proc_stock','proc_stock_inbound'):
            check(conn.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table+' denies reads without tenant context')
        with conn.transaction():tenant();insert(rid,payload)
        check(sql(clone,"SELECT source_revision,usable,reserved,quarantine FROM proc_stock WHERE id='"+rid+"'")=='1|10|5|2',
              'Stock creation synchronizes balances and revision immediately')
        check(sql(clone,"SELECT string_agg(source_snapshot->>'reference',',' ORDER BY line_index) FROM proc_stock_inbound WHERE stock_id='"+rid+"'")=='mock-A,mock-B',
              'Inbound projection preserves source order and extension fields')
        with conn.transaction():tenant('other');insert(other,payload,'other')
        for parent,label in ((rid+'-missing','Inbound rows require a parent stock record'),
                             (other,'Cross-tenant inbound parent links are rejected')):
            statement="INSERT INTO public.proc_stock_inbound VALUES('demo','"+parent+"',0,1,true,'2030-01-01','{}');"
            check(sql(clone,statement,expected_error=True)=='23503',label)
        for table,column in (('proc_stock','id'),('proc_stock_inbound','stock_id')):
            with conn.transaction():
                tenant();check(conn.execute('SELECT count(*) FROM '+table+' WHERE '+column+'=%s',(other,)).fetchone()[0]==0,
                               table+' hides the other tenant fixture')
            with conn.transaction():
                tenant('other');check(conn.execute('SELECT count(*) FROM '+table+' WHERE '+column+'=%s',(other,)).fetchone()[0]>0,
                                      table+' exposes its own second-tenant fixture')
            check(conn.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table+' clears tenant context after commit')
        changed=deepcopy(payload);changed.update(usable=12,reserved=25,quarantine=0)
        changed['inbound']=list(reversed(changed['inbound']))
        with conn.transaction():tenant();change(changed)
        check(sql(clone,"SELECT source_revision,usable,reserved,quarantine FROM proc_stock WHERE id='"+rid+"'")=='2|12|25|0',
              'Reservations can include confirmed inbound without requiring reserved below usable')
        check(sql(clone,"SELECT string_agg(source_snapshot->>'reference',',' ORDER BY line_index) FROM proc_stock_inbound WHERE stock_id='"+rid+"'")=='mock-B,mock-A',
              'Inbound replacement synchronizes values and order')
        valid=snapshot()
        invalid=[]
        for field,value in (('usable',-1),('reserved',-1),('quarantine',-1),('usable',1.5),('reserved','5'),
                            ('sku',''),('source',None),('as_of',None),('as_of','infinity'),('inbound',{})):
            body=deepcopy(changed);body[field]=value;invalid.append((body,{'23514'},'Invalid '+field+' value '+repr(value)+' rejected'))
        for field,value in (('quantity',0),('quantity',-1),('quantity',1.5),('confirmed','true'),('date','2030-02-30')):
            body=deepcopy(changed);body['inbound'][0][field]=value
            invalid.append((body,{'23514','22008'},'Invalid inbound '+field+' '+repr(value)+' rejected'))
        for body,codes,label in invalid:
            expect(lambda b=body:change(b),codes,label)
            check(snapshot()==valid,'Rejected edit preserves source revision, balances and inbound rows')
        expect(lambda:conn.execute("UPDATE records SET kind='document' WHERE id=%s",(rid,)),{'23514'},'Stock kind changes are rejected')
        expect(lambda:conn.execute('UPDATE records SET id=%s WHERE id=%s',(rid+'-moved',rid)),{'23514'},'Stock identity changes are rejected')
        for table in ('proc_stock','proc_stock_inbound'):
            expect(lambda t=table:conn.execute('DELETE FROM '+t),{'42501'},table+' blocks direct runtime writes')
        expect(lambda:conn.execute('SELECT public.sync_procurement_stock()'),{'42501'},'Runtime cannot directly execute the synchronization function')
        with conn.transaction():
            tenant();result=conn.execute('UPDATE records SET revision=revision+1 WHERE id=%s',(other,))
            check(result.rowcount==0,'Cross-tenant source update cannot reach another inventory record')
        try:
            with conn.transaction():
                tenant();change(dict(changed,usable=99))
                conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) VALUES(%s,'demo','buyer','inventory.rehearsal',%s,'{}','2030-01-01')",(rid+'-audit',rid))
                raise RuntimeError('intentional-rehearsal-rollback')
        except RuntimeError as error:
            if str(error)!='intentional-rehearsal-rollback':raise
        check(snapshot()==valid,'Outer rollback restores stock source and both projections')
        check(sql(clone,"SELECT count(*) FROM audit WHERE id='"+rid+"-audit'")=='0','Outer rollback removes its accompanying audit insert')
        empty=deepcopy(changed);empty['inbound']=[]
        with conn.transaction():tenant();change(empty)
        check(sql(clone,"SELECT count(*) FROM proc_stock_inbound WHERE stock_id='"+rid+"'")=='0','Empty inbound list removes previous delivery projections')
        with conn.transaction():tenant();conn.execute('DELETE FROM records WHERE id=%s',(rid,))
        for table,column in (('proc_stock','id'),('proc_stock_inbound','stock_id')):
            check(sql(clone,'SELECT count(*) FROM '+table+' WHERE '+column+"='"+rid+"'")=='0',table+' is cleaned when its source is deleted')
        with conn.transaction():tenant('other');conn.execute('DELETE FROM records WHERE id=%s',(other,))
    check(hashes(clone)==clone_before,'Every original table remains unchanged after fixture cleanup')
