def _storage_cases(sql,clone,conn,package,hashes,clone_before):
    from copy import deepcopy
    from decimal import Decimal
    import json
    from uuid import uuid4
    import psycopg
    from psycopg.types.json import Jsonb
    passed=[]
    def check(ok,label):
        if not ok:raise AssertionError(label)
        passed.append(label);print('PASS:',label,flush=True)
    rid='customer-quote-fixture-'+uuid4().hex[:10]
    parent=sql(clone,"SELECT id FROM proc_plans WHERE tenant='demo' ORDER BY id LIMIT 1")
    base={'plan_id':parent,'net':'10000.00','cost':'7250.00','contribution':'2750.00',
          'margin_pct':'27.50','status':'draft_requires_commercial_review','sent':False,
          'note':'Synthetic material/freight only — اختبار; tax and overhead excluded',
          'extension':{'sequence':[2,1,2]},'history':[{'revision':0,'note':'preserved'}]}
    loss=dict(base,net='1000.00',contribution='-6250.00',margin_pct='-625.00')
    zero=dict(base,cost='0.00',contribution='10000.00',margin_pct='100.00')
    rounding=dict(base,net='32.00',cost='31.00',contribution='1.00',margin_pct='3.12')
    def tenant(scope='demo'):conn.execute("SELECT set_config('supplypilot.tenant',%s,true)",(scope,))
    def insert(identity,data,scope='demo',kind='customer_quote'):
        conn.execute("INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) "
            "VALUES(%s,%s,%s,1,%s,'2030-01-01','2030-01-01')",(identity,scope,kind,Jsonb(data)))
    def change(data):
        conn.execute('UPDATE records SET revision=revision+1,data=%s WHERE id=%s',(Jsonb(data),rid))
    with conn.transaction():
        tenant();insert(rid,base);insert(rid+'-loss',loss);insert(rid+'-zero',zero);insert(rid+'-rounding',rounding)
    seeded=hashes(clone)
    check(hashes(clone)==seeded,'Existing checkpoint remains unchanged after fixture synchronization')
    expected="""SELECT tenant,id,revision,data->>'plan_id',(data->>'net')::numeric,
        (data->>'cost')::numeric,(data->>'contribution')::numeric,(data->>'margin_pct')::numeric,
        data->>'status',(data->>'sent')::boolean,data->>'note',data::jsonb
        FROM records WHERE kind='customer_quote'"""
    check(sql(clone,'WITH expected AS ('+expected+'), actual AS (SELECT * FROM proc_customer_quotes) '
        'SELECT count(*) FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) '
        'UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)) differences')=='0',
        'Backfill preserves every commercial field and complete source snapshot')
    check(sql(clone,"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.proc_customer_quotes'::regclass")=='t',
          'Customer-quote projection has enabled and forced tenant RLS')
    check(sql(clone,"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.sync_procurement_customer_quote()'::regprocedure")=='supplypilot_migrator',
          'Customer-quote synchronization uses the dedicated migration owner')
    check(sql(clone,"SELECT count(*) FROM proc_orders WHERE status='closed' AND total=7250.00")=='1',
          'Existing closed AED 7250 order is preserved')
    check(conn.execute('SELECT count(*) FROM proc_customer_quotes').fetchone()[0]==0,
          'No tenant context hides all customer quotes')
    check(Decimal(sql(clone,"SELECT contribution FROM proc_customer_quotes WHERE id='"+rid+"-loss'"))==Decimal('-6250.00'),
          'Negative contribution and margin remain valid commercial drafts')
    check(Decimal(sql(clone,"SELECT cost FROM proc_customer_quotes WHERE id='"+rid+"-zero'"))==0,
          'Zero-purchase cost snapshots remain representable')
    check(Decimal(sql(clone,"SELECT margin_pct FROM proc_customer_quotes WHERE id='"+rid+"-rounding'"))==Decimal('3.12'),
          'Application half-even margin snapshot is preserved without SQL recalculation')
    revised=deepcopy(base);revised.update(net='9000.00',contribution='1750.00',margin_pct='19.44')
    with conn.transaction():tenant();change(revised)
    check(sql(clone,"SELECT source_revision FROM proc_customer_quotes WHERE id='"+rid+"'")=='2',
          'Commercial snapshot updates synchronize revision in the source transaction')
    check(json.loads(sql(clone,"SELECT source_snapshot::text FROM proc_customer_quotes WHERE id='"+rid+"'"))==revised,
          'Unicode notes, original decimal strings, extensions and history survive synchronization')
    def snapshot():
        return tuple(sql(clone,"SELECT md5(row_to_json(r)::text) FROM "+table+" r WHERE id='"+rid+"'")
                     for table in ('records','proc_customer_quotes'))
    valid=snapshot()
    def expect(action,codes,label):
        rejected=False
        try:
            with conn.transaction():tenant();action();conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
        except psycopg.Error as error:
            if error.sqlstate not in codes:raise
            rejected=True
        check(rejected,label)
    for key,value in [('net','0.00'),('net','-1.00'),('cost','-1.00'),('contribution','0.00'),
        ('net','NaN'),('cost','Infinity'),('margin_pct','-Infinity'),('net','1.001'),
        ('net',9000),('cost',None),('contribution',True),('margin_pct',None),
        ('status','sent'),('status',None),('sent',True),('sent','false'),('sent',None),
        ('plan_id',None),('plan_id',''),('note',None)]:
        body=deepcopy(revised);body[key]=value
        codes={'23514','23503'} if key=='plan_id' else {'23514'}
        expect(lambda b=body:change(b),codes,'Invalid '+key+' value '+repr(value)+' rejected')
        check(snapshot()==valid,'Rejected edit preserves source, revision and full quote projection')
    missing=deepcopy(revised);missing.pop('net')
    expect(lambda:change(missing),{'23514'},'Missing required decimal field rejected')
    # A genuine second-tenant plan gives the foreign-key test a valid parent
    # that is invisible to the demo tenant, rather than merely a missing ID.
    foreign_rfq=rid+'-rfq';foreign_plan=rid+'-plan';other=rid+'-other'
    rfq=json.loads(sql(clone,"SELECT data::text FROM records WHERE tenant='demo' AND kind='rfq' ORDER BY id LIMIT 1"))
    rfq['invited']=[]
    plan={'rfq_id':foreign_rfq,'creator':'other-buyer','status':'pending','digest':'a'*64,
          'payload':{'rfq_id':foreign_rfq,'rfq_revision':1,'total':'0.00','budget':'10000.00',
                     'currency':'AED','objective':'cost','allocations':[],'stock_refs':{},'shortages':{}}}
    with conn.transaction():
        tenant('other');insert(foreign_rfq,rfq,'other','rfq');insert(foreign_plan,plan,'other','plan')
        insert(other,dict(base,plan_id=foreign_plan),'other')
    for linked in (foreign_plan,'missing-customer-quote-plan'):
        expect(lambda p=linked:insert(rid+'-bad-parent',dict(base,plan_id=p)),{'23503'},
               'Missing or cross-tenant sourcing-plan link rejected')
    with conn.transaction():
        tenant();check(conn.execute('SELECT count(*) FROM proc_customer_quotes WHERE id=%s',(other,)).fetchone()[0]==0,
                       'Demo tenant cannot read the foreign customer quote')
        check(conn.execute('UPDATE records SET revision=revision+1 WHERE id=%s',(other,)).rowcount==0,
              'Cross-tenant source update is blocked')
    with conn.transaction():
        tenant('other');check(conn.execute('SELECT count(*) FROM proc_customer_quotes WHERE id=%s',(other,)).fetchone()[0]==1,
                              'Second tenant can read its own customer quote')
    check(conn.execute('SELECT count(*) FROM proc_customer_quotes').fetchone()[0]==0,
          'Customer-quote tenant context clears after commit')
    for query in ('DELETE FROM proc_customer_quotes','UPDATE proc_customer_quotes SET sent=false',
                  'INSERT INTO proc_customer_quotes SELECT * FROM proc_customer_quotes'):
        expect(lambda q=query:conn.execute(q),{'42501'},'Projection blocks direct runtime writes')
    expect(lambda:conn.execute('SELECT public.sync_procurement_customer_quote()'),{'42501'},
           'Runtime cannot directly execute customer-quote synchronization')
    expect(lambda:conn.execute("UPDATE records SET kind='feedback' WHERE id=%s",(rid,)),{'23514'},
           'Customer-quote kind changes are rejected')
    expect(lambda:conn.execute('UPDATE records SET id=%s WHERE id=%s',(rid+'-moved',rid)),{'23514'},
           'Customer-quote identity changes are rejected')
    class RollbackProbe(Exception):pass
    try:
        with conn.transaction():
            tenant();change(base)
            conn.execute("INSERT INTO audit(id,tenant,actor,action,resource,details,at) "
                "VALUES(%s,'demo','buyer','quote.rehearsal',%s,'{}','2030-01-01')",(rid+'-audit',rid))
            raise RollbackProbe()
    except RollbackProbe:pass
    check(snapshot()==valid,'Outer rollback restores source revision and complete commercial snapshot')
    check(sql(clone,"SELECT count(*) FROM audit WHERE id='"+rid+"-audit'")=='0',
          'Outer rollback removes its accompanying audit insert')
    with conn.transaction():
        tenant()
        for identity in (rid,rid+'-loss',rid+'-zero',rid+'-rounding'):conn.execute('DELETE FROM records WHERE id=%s',(identity,))
    with conn.transaction():
        tenant('other')
        for identity in (other,foreign_plan,foreign_rfq):conn.execute('DELETE FROM records WHERE id=%s',(identity,))
    check(sql(clone,"SELECT count(*) FROM proc_customer_quotes WHERE id LIKE '"+rid+"%'")=='0',
          'Deleting customer-quote sources cleans every fixture projection')
    check(hashes(clone)==clone_before,'Every original table remains unchanged after fixture cleanup')
    return passed


def customer_quote_checks(sql,runtime_args,check):
    import psycopg
    clone='supplypilot_dev'
    tables=sql(clone,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    def hashes(database):
        return {t:sql(database,'SELECT md5(row_to_json(r)::text) FROM public.'+t+' r ORDER BY 1') for t in tables}
    before=hashes(clone)
    with psycopg.connect(**runtime_args,autocommit=True) as conn:
        results=_storage_cases(sql,clone,conn,None,hashes,before)
    for label in results:check(True,label)
