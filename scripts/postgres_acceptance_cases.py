"""Procurement API and relational read acceptance cases."""
from datetime import date,timedelta
from decimal import Decimal
import json
from uuid import uuid4

def workflow(client, password, check, race=None):
    tokens = {}
    for role in ('buyer','technical','manager','warehouse','finance','auditor',
                 'supplier-gulf','supplier-desert','other-buyer'):
        response = client.post('/api/v1/auth/login', json={'username':role,'password':password})
        check(response.status_code == 200, 'API login succeeds for '+role)
        tokens[role] = {'Authorization':'Bearer '+response.json()['access_token']}

    def request(method, path, role='buyer', payload=None, status=200, **kwargs):
        response = client.request(method, '/api/v1'+path, headers=tokens[role],
                                  **({'json':payload} if payload is not None else {}), **kwargs)
        if response.status_code != status:
            raise AssertionError(f'{method} {path}: expected {status}, received {response.status_code}: {response.text[:600]}')
        return response.json()

    def post(path, payload, role='buyer', status=200):
        return request('POST', path, role, payload, status)

    def record(rid):
        result=request('GET','/record/'+rid)
        if result['kind'] in ('order','receipt','invoice','stock','plan','exception','document','job'):
            from fastapi.encoders import jsonable_encoder
            from supplypilot.db import Session
            from supplypilot.security import lookup_identity
            from supplypilot.domain import get,view
            with Session() as db:
                user=lookup_identity(db,'buyer',by_username=True)
                expected=jsonable_encoder(view(get(db,user,rid),user))
            check(result==expected,result['kind']+' detail matches authoritative fields at revision '+str(result['revision']))
        return result

    suffix = uuid4().hex[:10]
    sku = 'WF-'+suffix
    specs = {'grade':'ASTM A106 Grade B','size':'DN50','schedule':'40','construction':'seamless'}
    evidence_text = ('SYNTHETIC WORKFLOW TEST ONLY - NOT A REAL CERTIFICATE\n'
                     f'SKU: {sku}\nQuantity: 55\nGrade: ASTM A106 Grade B\n'
                     'Size: DN50\nSchedule: 40\nConstruction: seamless\n')
    def upload(role):
        return request('POST','/documents',role,status=201,
                       files={'file':('workflow-demo.txt',evidence_text.encode(),'text/plain')})
    source = upload('buyer')
    check(source['data']['status']=='review_required','Buyer source upload parses through the API')
    line = {'sku':sku,'quantity':55,'unit':'piece','specs':specs,'evidence_id':source['id']}
    due = (date.today()+timedelta(days=30)).isoformat()
    rfq = post('/rfqs',{'title':'API rehearsal '+suffix,'due_date':due,'lines':[line]},status=201)
    check(rfq['data']['status']=='draft','API creates a new draft requirement')
    rfq = post('/rfqs/'+rfq['id']+'/review',{'expected_revision':rfq['revision'],
               'lines':[line],'reason':'Reviewed synthetic source fields for isolated workflow test'})
    check(rfq['data']['status']=='validated','API review validates the requirement')
    rfq = post('/rfqs/'+rfq['id']+'/invite',{'expected_revision':rfq['revision'],
                                                    'supplier_ids':['gulf','desert']})
    invitations = request('GET','/records/rfq','supplier-gulf')['items']
    check(any(x['id']==rfq['id'] for x in invitations),'Invited supplier can read the new requirement')
    request('GET','/record/'+rfq['id'],'other-buyer',status=404)
    check(True,'Other tenant cannot read the new requirement')
    offers=[]
    for supplier,qty,price,freight in (('gulf',30,'120.00','5.00'),('desert',25,'128.00','12.00')):
        doc=upload('supplier-'+supplier)
        quote=post('/offers',{'rfq_id':rfq['id'],'supplier_id':supplier,'sku':sku,'quantity':qty,
            'unit_price':price,'freight_per_piece':freight,'valid_until':due,
            'delivery_date':(date.today()+timedelta(days=10)).isoformat(),
            'specs':specs,'evidence_id':doc['id'],'recipient':supplier+'@example.invalid',
            'terms':'Synthetic net 30; local simulator only'},'supplier-'+supplier,201)
        check(quote['data']['compliance']['status']=='unknown',supplier+' quotation requires technical review')
        from supplypilot.schemas import OfferCreate
        revised_body={k:v for k,v in quote['data'].items() if k in OfferCreate.model_fields}
        revised_body['expected_revision']=quote['revision']
        quote=post('/offers',revised_body,'supplier-'+supplier,201)
        reread=record(quote['id'])
        check(reread==quote and len(reread['data']['history'])==1,
              supplier+' revised quotation history survives relational detail reads')
        assessed=post('/offers/'+quote['id']+'/assess',{'expected_revision':quote['revision'],
            'certificate_verified':True,'reason':'Mock evidence reviewed for simulated workflow only'},'technical')
        check(assessed['data']['compliance']['status']=='compliant',supplier+' mock assessment passes')
        offers.append(assessed)
    plan=post('/plans',{'rfq_id':rfq['id'],'expected_revision':rfq['revision'],
                       'objective':'cost','budget':'10000.00'},status=201)
    check(Decimal(plan['data']['payload']['total'])==Decimal('7250.00'),
          'API sourcing creates the expected AED 7250 purchase scenario')
    check(record(plan['id'])==plan,'Pending plan response matches relational detail')
    check(len(plan['data']['payload']['allocations'])==2,'Scenario includes both supplier allocations')
    post('/plans/'+plan['id']+'/decision',{'expected_revision':plan['revision'],
         'decision':'approved','reason':'Buyer must not approve this scenario'},'buyer',403)
    check(True,'Buyer cannot approve a purchasing scenario')
    plan=post('/plans/'+plan['id']+'/decision',{'expected_revision':plan['revision'],
         'decision':'approved','reason':'Synthetic budget and evidence approved by separate manager'},'manager')
    check(record(plan['id'])==plan,'Approved plan response matches relational detail')
    key='workflow-'+suffix
    execute={'expected_revision':plan['revision'],'key':key}
    if race:
        outcomes=race(client,tokens,plan['id'],'/plans/'+plan['id']+'/execute',
                      [execute,execute],'buyer',[202,202],'Duplicate execution')
        check(outcomes[0].json()['id']==outcomes[1].json()['id'],
              'Concurrent duplicate keys return the same durable intent')
        intent=outcomes[0].json()
    else:
        intent=post('/plans/'+plan['id']+'/execute',execute,status=202)
    check(record(plan['id'])['data']['status']=='execution_pending','Execution-pending plan reads synchronize')
    repeated=post('/plans/'+plan['id']+'/execute',execute,status=202)
    check(intent['id']==repeated['id'],'Repeated execution key returns the same intent')
    uncertain=post('/executions/'+intent['id']+'/dispatch',{'simulate_timeout':True})
    check(uncertain['state']=='uncertain','Simulated timeout persists an uncertain execution')
    if race:
        outcomes=race(client,tokens,intent['id'],'/executions/'+intent['id']+'/reconcile',
                      [{},{}],'buyer',[200,200],'Duplicate reconciliation',lock_table='outbox')
        check(outcomes[0].json()['external_id']==outcomes[1].json()['external_id'],
              'Concurrent reconciliation returns one external order identity')
        confirmed=outcomes[0].json()
    else:
        confirmed=post('/executions/'+intent['id']+'/reconcile',{})
    check(confirmed['state']=='confirmed','Reconciliation confirms the durable simulator purchase')
    again=post('/executions/'+intent['id']+'/reconcile',{})
    check(again['external_id']==confirmed['external_id'],'Repeated reconciliation returns the same external order')
    check(record(plan['id'])['data']['status']=='executed','Executed plan reads synchronize')
    orders=request('GET','/records/order')['items']
    case_orders=[x for x in orders if x['data']['plan_id']==plan['id']]
    check(len(case_orders)==1,'Reconciliation creates exactly one local purchase order')
    order=case_orders[0]; oid=order['id']
    request('GET','/record/'+oid,'other-buyer',status=404)
    check(True,'Other tenant cannot read the new order')
    indexes={x['supplier_id']:i for i,x in enumerate(order['data']['lines'])}
    def receipt(supplier,qty):
        o=record(oid)
        payload={'order_id':oid,'expected_revision':o['revision'],
            'allocation_index':indexes[supplier],'accepted':qty,'rejected':0,'quarantine':0,
            'evidence_id':source['id']}
        if race and supplier=='gulf':
            outcomes=race(client,tokens,oid,'/receipts',[payload,payload],
                          'warehouse',[201,409],'Competing receipts')
            saved=next(r.json() for r in outcomes if r.status_code==201)
            check(record(oid)['revision']==o['revision']+1,
                  'Competing receipts advance the order revision exactly once')
            return saved
        return post('/receipts',payload,'warehouse',201)
    def invoice(supplier,qty,price):
        o=record(oid)
        payload={'order_id':oid,'expected_revision':o['revision'],
            'allocation_index':indexes[supplier],'invoice_number':'WF-'+supplier+'-'+suffix,
            'quantity':qty,'unit_price':price,'evidence_id':source['id']}
        if race and supplier=='gulf':
            competitor=dict(payload,invoice_number=payload['invoice_number']+'-competitor')
            outcomes=race(client,tokens,oid,'/invoices',[payload,competitor],
                          'finance',[201,409],'Competing invoices')
            saved=next(r.json() for r in outcomes if r.status_code==201)
            check(record(oid)['revision']==o['revision']+1,
                  'Competing invoices advance the order revision exactly once')
            return saved
        return post('/invoices',payload,'finance',201)
    gulf_receipt=receipt('gulf',30)
    inventory=request('GET','/records/stock','warehouse')['items']
    received_stock=next(x for x in inventory if x['data']['sku']==sku)
    check(record(received_stock['id'])['data']['usable']==30,
          'Inventory relational reads expose the first receipt stock balance')
    check(record(gulf_receipt['id'])==gulf_receipt,'New receipt detail matches creation response')
    good=invoice('gulf',30,'120.00')
    check(record(good['id'])==good,'Matched invoice detail matches creation response')
    check(good['data']['status']=='matched','Received Gulf material invoice matches through API')
    bad=invoice('desert',25,'128.00')
    check(record(bad['id'])==bad,'Mismatched invoice detail matches creation response')
    check(bad['data']['status']=='mismatch','Desert invoice remains mismatched before receipt')
    o=record(oid)
    post('/orders/'+oid+'/close',{'expected_revision':o['revision']},status=409)
    check(True,'Incomplete receipt prevents order closure')
    receipt('desert',25)
    updated_stock=record(received_stock['id'])
    check(updated_stock['data']['usable']==55 and updated_stock['revision']==2,
          'Inventory relational reads expose the second receipt and revision')
    rechecked=post('/invoices/'+bad['id']+'/recheck',{'expected_revision':bad['revision'],
        'expected_order_revision':record(oid)['revision'],
        'reason':'Missing synthetic receipt recorded; recheck same invoice facts'},'finance')
    check(record(rechecked['id'])==rechecked,'Rechecked invoice detail preserves prior assessment and facts')
    check(rechecked['id']==bad['id'] and rechecked['data']['status']=='matched',
          'API recheck matches the original invoice after receipt')
    check(rechecked['data']['assessment_history'][0]['data']['status']=='mismatch',
          'Recheck retains the prior mismatched assessment')
    check(all(rechecked['data'][k]==bad['data'][k] for k in
          ('invoice_number','quantity','unit_price','evidence_id','supplier_id')),
          'Recheck preserves invoice facts')
    cases=request('GET','/records/exception','finance')['items']
    relevant=[x for x in cases if x['data']['resource_id']==bad['id']]
    check(record(relevant[0]['id'])['data']['status']=='resolved','Automatic invoice resolution is visible in exception relational detail')
    check(len(relevant)==1 and relevant[0]['data']['status']=='resolved',
          'Successful recheck resolves its generated matching exception')
    o=record(oid)
    closed=post('/orders/'+oid+'/close',{'expected_revision':o['revision']})
    check(closed['data']['status']=='closed','Fully received and matched order closes through API')
    check(record(oid)==closed,'Closed order mutation and relational detail responses match')
    events=request('GET','/audit','auditor')
    check(any(x['action']=='order.closed' and x['resource']==oid for x in events),
          'Auditor can read the new order closure event')
    job_workflow(client,password,check,tokens)
    document_workflow(client,password,check,tokens)
    exception_workflow(client,password,check,tokens)
    return {'intent_id':intent['id'],'rfq_id':rfq['id'],'order_id':oid,'sku':sku,'external_id':confirmed['external_id'],
            'invoice_ids':[good['id'],rechecked['id']]}



def read_checks(client,password,check,sql,clone):
    from supplypilot.db import Session
    from supplypilot.security import lookup_identity
    from supplypilot.domain import records,view,get
    tokens={}
    for role in ('buyer','warehouse','finance','supplier-gulf','supplier-desert','other-buyer','auditor','manager'):
        response=client.post('/api/v1/auth/login',json={'username':role,'password':password})
        if response.status_code!=200:raise AssertionError('Read comparison login failed for '+role)
        tokens[role]={'Authorization':'Bearer '+response.json()['access_token']}
        for kind in ('supplier','rfq','offer','order','receipt','invoice','stock','plan','exception','document','job'):
            with Session() as db:
                user=lookup_identity(db,role,by_username=True)
                rows=records(db,user,kind)
                rows.sort(key=lambda r:r.id)
                rows.sort(key=lambda r:r.created_at,reverse=True)
                expected=[view(r,user) for r in rows]
            response=client.get('/api/v1/records/'+kind,headers=tokens[role])
            check(response.status_code==200 and response.json()=={
                'items':expected,'total':len(expected),'offset':0,'limit':100},
                role+' '+kind+' collection matches the legacy response')
            response=client.get('/api/v1/records/'+kind+'?offset=1&limit=1',headers=tokens[role])
            check(response.status_code==200 and response.json()=={
                'items':expected[1:2],'total':len(expected),'offset':1,'limit':1},
                role+' '+kind+' pagination preserves values and total')
            response=client.get('/api/v1/records/'+kind+'?offset=100000&limit=1',headers=tokens[role])
            check(response.status_code==200 and response.json()['items']==[] and response.json()['total']==len(expected),
                role+' '+kind+' empty page preserves total')
            for item in expected:
                detail=client.get('/api/v1/record/'+item['id'],headers=tokens[role])
                check(detail.status_code==200 and detail.json()==item,
                    role+' '+kind+' detail matches '+item['id'])
                if kind=='document':
                    with Session() as db:
                        scoped=lookup_identity(db,role,by_username=True)
                        source=get(db,scoped,item['id'],'document')
                        evidence_expected={'document_id':source.id,'sha256':source.data['sha256'],
                            'pages':source.data.get('pages',[]),'parser':source.data['parser']}
                    evidence_response=client.get('/api/v1/documents/'+item['id']+'/evidence',headers=tokens[role])
                    check(evidence_response.status_code==200 and evidence_response.json()==evidence_expected,
                          role+' document evidence matches exact authoritative parsed pages')
                    check('pages' not in item['data'],role+' document metadata excludes parsed pages')

    response=client.get('/api/v1/record/gulf',headers=tokens['supplier-gulf'])
    check(response.status_code==404,'Supplier cannot read an internal supplier master record')
    response=client.get('/api/v1/records/rfq?limit=201',headers=tokens['buyer'])
    check(response.status_code==422,'Read page size remains bounded')
    foreign=client.get('/api/v1/record/offer-desert',headers=tokens['supplier-gulf'])
    check(foreign.status_code==404,'Gulf supplier cannot read Desert quotation detail')
    offers=client.get('/api/v1/records/offer',headers=tokens['supplier-gulf']).json()['items']
    check(all(x['data']['supplier_id']=='gulf' for x in offers),'Supplier quotation collection excludes competitors')
    check(any(x['data']['quantity']==0 for x in offers),'Fully committed zero-capacity quotation remains visible')
    probe=sql(clone,"SELECT id FROM proc_offers WHERE tenant='demo' AND supplier_id='gulf' ORDER BY id LIMIT 1")
    original_terms=sql(clone,"SELECT terms FROM proc_offers WHERE tenant='demo' AND id='"+probe+"'")
    try:
        sql(clone,"UPDATE proc_offers SET terms='Projection quotation probe' WHERE tenant='demo' AND id='"+probe+"'")
        response=client.get('/api/v1/record/'+probe,headers=tokens['buyer'])
        check(response.status_code==200 and response.json()['data']['terms']=='Projection quotation probe',
              'Quotation detail reads normalized commercial terms')
        response=client.get('/api/v1/records/offer',headers=tokens['buyer'])
        check(any(x['id']==probe and x['data']['terms']=='Projection quotation probe' for x in response.json()['items']),
              'Quotation collection reads normalized commercial terms')
    finally:
        escaped_terms=original_terms.replace("'","''")
        sql(clone,"UPDATE proc_offers SET terms='"+escaped_terms+"' WHERE tenant='demo' AND id='"+probe+"'")
    try:
        sql(clone,"UPDATE proc_offers SET source_revision=source_revision+1 WHERE tenant='demo' AND id='"+probe+"'")
        response=client.get('/api/v1/record/'+probe,headers=tokens['buyer'])
        check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
              'Stale quotation detail fails closed')
        response=client.get('/api/v1/records/offer',headers=tokens['buyer'])
        check(response.status_code==503,'Stale quotation collection fails closed')
    finally:
        sql(clone,"UPDATE proc_offers h SET source_revision=r.revision FROM records r WHERE r.tenant=h.tenant AND r.id=h.id AND h.tenant='demo' AND h.id='"+probe+"'")
    order_id=sql(clone,"SELECT id FROM proc_orders WHERE tenant='demo' ORDER BY id LIMIT 1")
    response=client.get('/api/v1/record/'+order_id,headers=tokens['supplier-gulf'])
    check(response.status_code==404,'Supplier cannot read internal purchase order detail')
    response=client.get('/api/v1/record/'+order_id,headers=tokens['other-buyer'])
    check(response.status_code==404,'Other tenant cannot read checkpoint purchase order')
    original_external=sql(clone,"SELECT external_id FROM proc_orders WHERE tenant='demo' AND id='"+order_id+"'")
    try:
        sql(clone,"UPDATE proc_orders SET external_id='SIM-READ-PROBE' WHERE tenant='demo' AND id='"+order_id+"'")
        response=client.get('/api/v1/record/'+order_id,headers=tokens['buyer'])
        check(response.status_code==200 and response.json()['data']['external_id']=='SIM-READ-PROBE',
              'Order detail consumes normalized header fields')
        response=client.get('/api/v1/records/order',headers=tokens['buyer'])
        check(any(x['id']==order_id and x['data']['external_id']=='SIM-READ-PROBE' for x in response.json()['items']),
              'Order collection consumes normalized header fields')
    finally:
        sql(clone,"UPDATE proc_orders SET external_id='"+original_external.replace("'","''")+"' WHERE tenant='demo' AND id='"+order_id+"'")
    # Snapshot extensions are deliberately not stored on the source in this probe.
    # This does not affect any balance constraint and is restored immediately.
    try:
        sql(clone,"UPDATE proc_order_lines SET approved_snapshot=approved_snapshot || '{\"read_probe\":\"snapshot\"}'::jsonb WHERE tenant='demo' AND order_id='"+order_id+"' AND line_index=0")
        response=client.get('/api/v1/record/'+order_id,headers=tokens['buyer'])
        check(response.status_code==200 and response.json()['data']['lines'][0].get('read_probe')=='snapshot',
              'Order lines consume normalized approved snapshots in allocation order')
    finally:
        sql(clone,"UPDATE proc_order_lines SET approved_snapshot=approved_snapshot-'read_probe' WHERE tenant='demo' AND order_id='"+order_id+"' AND line_index=0")
    try:
        sql(clone,"UPDATE proc_orders SET source_revision=source_revision+1 WHERE tenant='demo' AND id='"+order_id+"'")
        response=client.get('/api/v1/record/'+order_id,headers=tokens['buyer'])
        check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
              'Stale order detail fails closed')
        response=client.get('/api/v1/records/order',headers=tokens['buyer'])
        check(response.status_code==503,'Stale order collection fails closed')
    finally:
        sql(clone,"UPDATE proc_orders h SET source_revision=r.revision FROM records r WHERE r.tenant=h.tenant AND r.id=h.id AND h.tenant='demo' AND h.id='"+order_id+"'")
    for kind,table,column,probe_value in (
        ('receipt','proc_receipts','evidence_id','fulfillment-receipt-read-probe'),
        ('invoice','proc_invoices','tolerance','fulfillment-invoice-read-probe')):
        rid=sql(clone,"SELECT id FROM "+table+" WHERE tenant='demo' ORDER BY id LIMIT 1")
        for role in ('supplier-gulf','supplier-desert','other-buyer'):
            response=client.get('/api/v1/record/'+rid,headers=tokens[role])
            check(response.status_code==404,role+' cannot read internal '+kind+' detail')
        old_value=sql(clone,"SELECT "+column+" FROM "+table+" WHERE tenant='demo' AND id='"+rid+"'")
        try:
            sql(clone,"UPDATE "+table+" SET "+column+"='"+probe_value+"' WHERE tenant='demo' AND id='"+rid+"'")
            response=client.get('/api/v1/record/'+rid,headers=tokens['buyer'])
            check(response.status_code==200 and response.json()['data'][column]==probe_value,
                  kind+' detail consumes normalized ledger fields')
            response=client.get('/api/v1/records/'+kind,headers=tokens['buyer'])
            check(any(x['id']==rid and x['data'][column]==probe_value for x in response.json()['items']),
                  kind+' collection consumes normalized ledger fields')
        finally:
            sql(clone,"UPDATE "+table+" SET "+column+"='"+old_value.replace("'","''")+"' WHERE tenant='demo' AND id='"+rid+"'")
        try:
            sql(clone,"UPDATE "+table+" SET source_revision=source_revision+1 WHERE tenant='demo' AND id='"+rid+"'")
            response=client.get('/api/v1/record/'+rid,headers=tokens['buyer'])
            check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
                  'Stale '+kind+' detail fails closed')
            response=client.get('/api/v1/records/'+kind,headers=tokens['buyer'])
            check(response.status_code==503,'Stale '+kind+' collection fails closed')
        finally:
            sql(clone,"UPDATE "+table+" h SET source_revision=r.revision FROM records r WHERE r.tenant=h.tenant AND r.id=h.id AND h.tenant='demo' AND h.id='"+rid+"'")
    for kind,table,column,key in (
        ('receipt','proc_receipts','received_at','at'),
        ('invoice','proc_invoices','rechecked_at','rechecked_at'),
        ('order','proc_orders','closed_at','closed_at')):
        rid=sql(clone,"SELECT id FROM "+table+" WHERE tenant='demo' AND "+column+" IS NOT NULL ORDER BY id LIMIT 1")
        original_time=sql(clone,"SELECT "+column+"::text FROM "+table+" WHERE tenant='demo' AND id='"+rid+"'")
        try:
            sql(clone,"UPDATE "+table+" SET "+column+"='2026-11-02T00:00:00.123400+00:00' WHERE tenant='demo' AND id='"+rid+"'")
            detail=client.get('/api/v1/record/'+rid,headers=tokens['buyer'])
            page=client.get('/api/v1/records/'+kind,headers=tokens['buyer'])
            check(detail.status_code==200 and page.status_code==200,
                  kind+' fractional timestamp probe reads succeed')
            item=next(x for x in page.json()['items'] if x['id']==rid)
            check(item==detail.json() and item['data'][key]=='2026-11-02T00:00:00.123400+00:00',
                  kind+' collection and detail preserve trailing timestamp zeros')
        finally:
            sql(clone,"UPDATE "+table+" SET "+column+"='"+original_time.replace("'","''")+"' WHERE tenant='demo' AND id='"+rid+"'")
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        response=client.get('/api/v1/record/stock-demo',headers=tokens[role])
        check(response.status_code==404,role+' cannot read demo inventory detail')
    old_usable=sql(clone,"SELECT usable FROM proc_stock WHERE tenant='demo' AND id='stock-demo'")
    try:
        sql(clone,"UPDATE proc_stock SET usable=usable+1 WHERE tenant='demo' AND id='stock-demo'")
        detail=client.get('/api/v1/record/stock-demo',headers=tokens['buyer'])
        check(detail.status_code==200 and detail.json()['data']['usable']==int(old_usable)+1,
              'Inventory detail consumes normalized stock balances')
        page=client.get('/api/v1/records/stock',headers=tokens['buyer'])
        check(any(x['id']=='stock-demo' and x['data']['usable']==int(old_usable)+1 for x in page.json()['items']),
              'Inventory collection consumes normalized stock balances')
    finally:
        sql(clone,"UPDATE proc_stock SET usable="+old_usable+" WHERE tenant='demo' AND id='stock-demo'")
    saved_lines=sql(clone,"SELECT jsonb_agg(to_jsonb(l) ORDER BY line_index)::text FROM proc_stock_inbound l WHERE tenant='demo' AND stock_id='stock-demo'")
    try:
        sql(clone,"UPDATE proc_stock_inbound SET quantity=quantity+1 WHERE tenant='demo' AND stock_id='stock-demo' AND line_index=0")
        detail=client.get('/api/v1/record/stock-demo',headers=tokens['buyer'])
        expected=json.loads(saved_lines)[0]['quantity']+1
        check(detail.status_code==200 and detail.json()['data']['inbound'][0]['quantity']==expected,
              'Inventory detail consumes normalized inbound quantities')
        page=client.get('/api/v1/records/stock',headers=tokens['buyer'])
        check(next(x for x in page.json()['items'] if x['id']=='stock-demo')['data']['inbound'][0]['quantity']==expected,
              'Inventory collection consumes normalized inbound quantities')
    finally:
        sql(clone,"DELETE FROM proc_stock_inbound WHERE tenant='demo' AND stock_id='stock-demo'")
        sql(clone,"INSERT INTO proc_stock_inbound SELECT * FROM jsonb_populate_recordset(NULL::proc_stock_inbound,'"+saved_lines.replace("'","''")+"')")
    try:
        sql(clone,"DELETE FROM proc_stock_inbound WHERE tenant='demo' AND stock_id='stock-demo'")
        for path in ('/record/stock-demo','/records/stock'):
            response=client.get('/api/v1'+path,headers=tokens['buyer'])
            check(response.status_code==503,'Missing inbound rows fail closed for '+path)
    finally:
        sql(clone,"INSERT INTO proc_stock_inbound SELECT * FROM jsonb_populate_recordset(NULL::proc_stock_inbound,'"+saved_lines.replace("'","''")+"')")
    try:
        sql(clone,"UPDATE proc_stock SET source_revision=source_revision+1 WHERE tenant='demo' AND id='stock-demo'")
        for path in ('/record/stock-demo','/records/stock'):
            response=client.get('/api/v1'+path,headers=tokens['buyer'])
            check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
                  'Stale inventory fails closed for '+path)
    finally:
        sql(clone,"UPDATE proc_stock h SET source_revision=r.revision FROM records r WHERE r.tenant=h.tenant AND r.id=h.id AND h.tenant='demo' AND h.id='stock-demo'")
    original_time=sql(clone,"SELECT as_of::text FROM proc_stock WHERE tenant='demo' AND id='stock-demo'")
    try:
        sql(clone,"UPDATE proc_stock SET as_of='2026-11-02T00:00:00.123400+00:00' WHERE tenant='demo' AND id='stock-demo'")
        detail=client.get('/api/v1/record/stock-demo',headers=tokens['buyer'])
        page=client.get('/api/v1/records/stock',headers=tokens['buyer'])
        item=next(x for x in page.json()['items'] if x['id']=='stock-demo')
        check(item==detail.json() and item['data']['as_of']=='2026-11-02T00:00:00.123400+00:00',
              'Inventory collection and detail preserve timestamp precision')
    finally:
        sql(clone,"UPDATE proc_stock SET as_of='"+original_time.replace("'","''")+"' WHERE tenant='demo' AND id='stock-demo'")
    # Controlled corruption is confined to this disposable clone and restored in finally.
    # It proves relational field consumption and fail-closed stale revision behavior.
    rid='rfq-demo'
    original=sql(clone,"SELECT title FROM proc_rfqs WHERE tenant='demo' AND id='rfq-demo'")
    escaped=original.replace("'","''")
    try:
        sql(clone,"UPDATE proc_rfqs SET title='Projection read probe' WHERE tenant='demo' AND id='rfq-demo'")
        response=client.get('/api/v1/record/'+rid,headers=tokens['buyer'])
        check(response.status_code==200 and response.json()['data']['title']=='Projection read probe',
              'RFQ detail reads the relational title')
        response=client.get('/api/v1/records/rfq',headers=tokens['buyer'])
        check(any(x['id']==rid and x['data']['title']=='Projection read probe' for x in response.json()['items']),
              'RFQ collection reads the relational title')
    finally:
        sql(clone,"UPDATE proc_rfqs SET title='"+escaped+"' WHERE tenant='demo' AND id='rfq-demo'")
    try:
        sql(clone,"UPDATE proc_rfqs SET source_revision=source_revision+1 WHERE tenant='demo' AND id='rfq-demo'")
        response=client.get('/api/v1/record/'+rid,headers=tokens['buyer'])
        check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
              'Stale RFQ detail fails closed with an explicit error')
        response=client.get('/api/v1/records/rfq',headers=tokens['buyer'])
        check(response.status_code==503,'Stale RFQ collection fails closed')
    finally:
        sql(clone,"UPDATE proc_rfqs h SET source_revision=r.revision FROM records r WHERE r.tenant=h.tenant AND r.id=h.id AND h.tenant='demo' AND h.id='rfq-demo'")



    plan_id=sql(clone,"SELECT p.id FROM proc_plans p WHERE p.tenant='demo' AND NOT EXISTS (SELECT 1 FROM proc_customer_quotes q WHERE q.tenant=p.tenant AND q.plan_id=p.id) ORDER BY p.id LIMIT 1")
    saved=sql(clone,"SELECT to_jsonb(p)::text FROM proc_plans p WHERE tenant='demo' AND id='"+plan_id+"'")
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        response=client.get('/api/v1/record/'+plan_id,headers=tokens[role])
        check(response.status_code==404,role+' cannot read demo plan detail')
    def restore_plan():
        sql(clone,"DELETE FROM proc_plans WHERE tenant='demo' AND id='"+plan_id+"'")
        sql(clone,"INSERT INTO proc_plans SELECT * FROM jsonb_populate_record(NULL::proc_plans,'"+saved.replace("'","''")+"')")
    try:
        sql(clone,"UPDATE proc_plans SET reason='Relational plan probe',payload=payload || '{\"projection_extension\":{\"note\":\"retained\"}}'::jsonb WHERE tenant='demo' AND id='"+plan_id+"'")
        for path in ('/record/'+plan_id,'/records/plan'):
            response=client.get('/api/v1'+path,headers=tokens['buyer'])
            check(response.status_code==200,'Plan relational probe succeeds for '+path)
            item=response.json() if path.startswith('/record/') else next(x for x in response.json()['items'] if x['id']==plan_id)
            check(item['data']['reason']=='Relational plan probe' and item['data']['payload']['projection_extension']=={'note':'retained'},'Plan reads consume projected approval metadata and full payload for '+path)
    finally:restore_plan()
    for missing in (False,True):
        try:
            if missing:sql(clone,"DELETE FROM proc_plans WHERE tenant='demo' AND id='"+plan_id+"'")
            else:sql(clone,"UPDATE proc_plans SET source_revision=source_revision+1 WHERE tenant='demo' AND id='"+plan_id+"'")
            for path in ('/record/'+plan_id,'/records/plan'):
                response=client.get('/api/v1'+path,headers=tokens['buyer'])
                check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',('Missing' if missing else 'Stale')+' plan projection fails closed for '+path)
        finally:restore_plan()
    try:
        sql(clone,"UPDATE proc_plans SET expires_at='2020-01-01T00:00:00.123400+00:00' WHERE tenant='demo' AND id='"+plan_id+"'")
        detail=client.get('/api/v1/record/'+plan_id,headers=tokens['buyer'])
        page=client.get('/api/v1/records/plan',headers=tokens['buyer'])
        item=next(x for x in page.json()['items'] if x['id']==plan_id)
        check(detail.status_code==200 and item==detail.json() and item['data']['expires_at']=='2020-01-01T00:00:00.123400+00:00','Expired historical plan stays readable with exact timestamp precision')
    finally:restore_plan()

    exception_id=sql(clone,"SELECT id FROM proc_exceptions WHERE tenant='demo' ORDER BY id LIMIT 1")
    saved=sql(clone,"SELECT to_jsonb(e)::text FROM proc_exceptions e WHERE tenant='demo' AND id='"+exception_id+"'")
    def restore_exception():
        sql(clone,"DELETE FROM proc_exceptions WHERE tenant='demo' AND id='"+exception_id+"'")
        sql(clone,"INSERT INTO proc_exceptions SELECT * FROM jsonb_populate_record(NULL::proc_exceptions,'"+saved.replace("'","''")+"')")
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        response=client.get('/api/v1/record/'+exception_id,headers=tokens[role])
        check(response.status_code==404,role+' cannot read demo exception detail')
    try:
        sql(clone,"UPDATE proc_exceptions SET detail='Projected exception detail',source_snapshot=source_snapshot || '{\"read_extension\":{\"note\":\"retained\"}}'::jsonb WHERE tenant='demo' AND id='"+exception_id+"'")
        for path in ('/record/'+exception_id,'/records/exception'):
            response=client.get('/api/v1'+path,headers=tokens['finance'])
            check(response.status_code==200,'Exception relational probe succeeds for '+path)
            item=response.json() if path.startswith('/record/') else next(x for x in response.json()['items'] if x['id']==exception_id)
            check(item['data']['detail']=='Projected exception detail' and item['data']['read_extension']=={'note':'retained'},
                  'Exception reads consume projected fields and complete snapshot for '+path)
    finally:restore_exception()
    for missing in (False,True):
        try:
            if missing:sql(clone,"DELETE FROM proc_exceptions WHERE tenant='demo' AND id='"+exception_id+"'")
            else:sql(clone,"UPDATE proc_exceptions SET source_revision=source_revision+1 WHERE tenant='demo' AND id='"+exception_id+"'")
            for path in ('/record/'+exception_id,'/records/exception'):
                response=client.get('/api/v1'+path,headers=tokens['finance'])
                check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
                      ('Missing' if missing else 'Stale')+' exception fails closed for '+path)
        finally:restore_exception()
    timed=sql(clone,"SELECT id FROM proc_exceptions WHERE tenant='demo' AND resolved_at IS NOT NULL ORDER BY id LIMIT 1")
    original_time=sql(clone,"SELECT resolved_at::text FROM proc_exceptions WHERE tenant='demo' AND id='"+timed+"'")
    try:
        sql(clone,"UPDATE proc_exceptions SET resolved_at='2020-01-01T00:00:00.123400+00:00' WHERE tenant='demo' AND id='"+timed+"'")
        detail=client.get('/api/v1/record/'+timed,headers=tokens['finance'])
        page=client.get('/api/v1/records/exception',headers=tokens['finance'])
        item=next(x for x in page.json()['items'] if x['id']==timed)
        check(detail.status_code==200 and item==detail.json() and item['data']['resolved_at']=='2020-01-01T00:00:00.123400+00:00',
              'Historical exception resolution remains readable with exact timestamp precision')
    finally:
        sql(clone,"UPDATE proc_exceptions SET resolved_at='"+original_time.replace("'","''")+"' WHERE tenant='demo' AND id='"+timed+"'")


    document_id=sql(clone,"SELECT d.id FROM proc_documents d WHERE d.tenant='demo' AND d.page_count>0 AND NOT EXISTS (SELECT 1 FROM proc_document_jobs j WHERE j.tenant=d.tenant AND j.document_id=d.id) ORDER BY d.id LIMIT 1")
    saved_header=sql(clone,"SELECT to_jsonb(d)::text FROM proc_documents d WHERE tenant='demo' AND id='"+document_id+"'")
    saved_pages=sql(clone,"SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY page_index),'[]'::jsonb)::text FROM proc_document_pages p WHERE tenant='demo' AND document_id='"+document_id+"'")
    def restore_document():
        sql(clone,"DELETE FROM proc_document_pages WHERE tenant='demo' AND document_id='"+document_id+"'")
        sql(clone,"DELETE FROM proc_documents WHERE tenant='demo' AND id='"+document_id+"'")
        sql(clone,"INSERT INTO proc_documents SELECT * FROM jsonb_populate_record(NULL::proc_documents,'"+saved_header.replace("'","''")+"')")
        sql(clone,"INSERT INTO proc_document_pages SELECT * FROM jsonb_populate_recordset(NULL::proc_document_pages,'"+saved_pages.replace("'","''")+"')")
    for role in ('supplier-desert','other-buyer'):
        for path in ('/record/'+document_id,'/documents/'+document_id+'/evidence'):
            response=client.get('/api/v1'+path,headers=tokens[role])
            check(response.status_code==404,role+' cannot read demo document through '+path)
    try:
        sql(clone,"UPDATE proc_documents SET filename='projection-probe.txt',parser='projection-parser',source_snapshot=source_snapshot || '{\"read_extension\":{\"note\":\"retained\"}}'::jsonb WHERE tenant='demo' AND id='"+document_id+"'")
        for path in ('/record/'+document_id,'/records/document'):
            response=client.get('/api/v1'+path,headers=tokens['buyer'])
            check(response.status_code==200,'Document relational metadata probe succeeds for '+path)
            item=response.json() if path.startswith('/record/') else next(x for x in response.json()['items'] if x['id']==document_id)
            check(item['data']['filename']=='projection-probe.txt' and item['data']['read_extension']=={'note':'retained'} and 'pages' not in item['data'],
                  'Document metadata consumes projected fields and excludes pages for '+path)
        evidence=client.get('/api/v1/documents/'+document_id+'/evidence',headers=tokens['buyer'])
        check(evidence.status_code==200 and evidence.json()['parser']=='projection-parser','Evidence reads normalized parser metadata')
    finally:restore_document()
    try:
        pages=['Projected first page — اختبار','','Projected first page — اختبار']
        sql(clone,"UPDATE proc_documents SET page_count=3 WHERE tenant='demo' AND id='"+document_id+"'")
        sql(clone,"DELETE FROM proc_document_pages WHERE tenant='demo' AND document_id='"+document_id+"'")
        for index in (2,0,1):
            sql(clone,"INSERT INTO proc_document_pages VALUES('demo','"+document_id+"',"+str(index)+",'"+pages[index].replace("'","''")+"')")
        evidence=client.get('/api/v1/documents/'+document_id+'/evidence',headers=tokens['buyer'])
        check(evidence.status_code==200 and evidence.json()['pages']==pages,'Evidence consumes normalized pages in page-index order with Unicode, blanks and duplicates')
    finally:restore_document()
    paths=('/record/'+document_id,'/records/document','/documents/'+document_id+'/evidence')
    for corruption in ('stale header','missing page','extra page','missing header'):
        try:
            if corruption=='stale header':sql(clone,"UPDATE proc_documents SET source_revision=source_revision+1 WHERE tenant='demo' AND id='"+document_id+"'")
            elif corruption=='extra page':sql(clone,"INSERT INTO proc_document_pages VALUES('demo','"+document_id+"',59,'unexpected page')")
            else:
                sql(clone,"DELETE FROM proc_document_pages WHERE tenant='demo' AND document_id='"+document_id+"'")
                if corruption=='missing header':sql(clone,"DELETE FROM proc_documents WHERE tenant='demo' AND id='"+document_id+"'")
            for path in paths:
                response=client.get('/api/v1'+path,headers=tokens['buyer'])
                check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',corruption+' fails closed for '+path)
        finally:restore_document()
    try:
        sql(clone,"UPDATE proc_documents SET supplier_id='desert' WHERE tenant='demo' AND id='"+document_id+"'")
        for role in ('supplier-gulf','supplier-desert'):
            for path in ('/record/'+document_id,'/documents/'+document_id+'/evidence'):
                response=client.get('/api/v1'+path,headers=tokens[role])
                check(response.status_code==404,'Source/projection ownership disagreement denies '+role+' through '+path)
    finally:restore_document()


    job_read_probes(client,check,sql,clone,tokens)


def exception_workflow(client,password,check,tokens):
    from supplypilot.db import Session
    from supplypilot.security import lookup_identity
    from supplypilot.domain import get,view
    def request(method,path,role='buyer',body=None,status=200,**kwargs):
        response=client.request(method,'/api/v1'+path,headers=tokens[role],
            **({'json':body} if body is not None else {}),**kwargs)
        if response.status_code!=status:raise AssertionError(f'{method} {path}: {response.status_code}: {response.text[:500]}')
        return response.json()
    def parity(case,label):
        detail=request('GET','/record/'+case['id'])
        page=request('GET','/records/exception')
        with Session() as db:
            user=lookup_identity(db,'buyer',by_username=True)
            expected=view(get(db,user,case['id']),user)
        check(detail==case==expected and next(x for x in page['items'] if x['id']==case['id'])==case,label)
    doc=request('POST','/documents',status=201,files={'file':('exception-demo.txt',b'SYNTHETIC EXCEPTION EVIDENCE ONLY','text/plain')})
    body={'resource_id':doc['id'],'category':'read-rehearsal','detail':'Synthetic case lifecycle for relational reads',
          'owner':'buyer','due_date':'2030-01-01'}
    case=request('POST','/exceptions',body=body,status=201)
    parity(case,'New open exception collection and detail match creation and authoritative facts')
    duplicate=request('POST','/exceptions',body=body,status=201)
    check(duplicate['id']==case['id'],'Repeated open case creation returns its existing identity')
    for role in ('supplier-gulf','other-buyer'):request('GET','/record/'+case['id'],role,status=404)
    check(True,'Suppliers and other tenants cannot read the new exception')
    resolution={'expected_revision':case['revision'],'evidence_id':doc['id'],'reason':'Synthetic evidence reviewed by assigned owner'}
    request('POST','/exceptions/'+case['id']+'/resolve','technical',resolution,403)
    check(True,'An unrelated internal account cannot resolve another owner case')
    resolved=request('POST','/exceptions/'+case['id']+'/resolve',body=resolution)
    parity(resolved,'Manual resolution preserves exact evidence, reason and revision in relational reads')
    request('POST','/exceptions/'+case['id']+'/reopen',body={'expected_revision':resolved['revision']},status=403)
    reopened=request('POST','/exceptions/'+case['id']+'/reopen','manager',{'expected_revision':resolved['revision']})
    parity(reopened,'Manager reopening preserves prior resolution fields in relational reads')
    check(reopened['data']['resolution']==resolved['data']['resolution'] and reopened['data']['evidence_id']==doc['id'],
          'Reopening retains prior evidence and manual reason')
    resolution['expected_revision']=resolved['revision']
    request('POST','/exceptions/'+case['id']+'/resolve',body=resolution,status=409)
    check(request('GET','/record/'+case['id'])==reopened,'Stale resolution cannot change the exception')
    resolution['expected_revision']=reopened['revision']
    again=request('POST','/exceptions/'+case['id']+'/resolve',body=resolution)
    parity(again,'Re-resolved exception remains consistent across mutation, detail and collection reads')


def document_workflow(client,password,check,tokens):
    import hashlib
    marker='DOCREAD'+uuid4().hex[:10]
    text='SYNTHETIC DOCUMENT READ TEST ONLY\n'+marker+'\nUnicode — اختبار\nPIPE-DN50\n'
    raw=text.encode('utf-8')
    def request(method,path,role='buyer',status=200,**kwargs):
        response=client.request(method,'/api/v1'+path,headers=tokens[role],**kwargs)
        if response.status_code!=status:
            raise AssertionError(f'{method} {path}: expected {status}, got {response.status_code}: {response.text[:400]}')
        return response
    docs={}
    for role in ('buyer','supplier-gulf','supplier-desert'):
        result=request('POST','/documents',role,201,files={'file':('document-read-demo.txt',raw,'text/plain')}).json()
        docs[role]=result
        detail=request('GET','/record/'+result['id'],role).json()
        page=request('GET','/records/document',role).json()
        check(detail==result==next(x for x in page['items'] if x['id']==result['id']),role+' new document metadata matches creation, collection and detail')
        check('pages' not in detail['data'] and 'pages' not in next(x for x in page['items'] if x['id']==result['id'])['data'],role+' document metadata does not expose parsed page text')
        evidence=request('GET','/documents/'+result['id']+'/evidence',role).json()
        check(evidence=={'document_id':result['id'],'sha256':hashlib.sha256(raw).hexdigest(),'pages':[text],'parser':'pypdf/text-v1'},role+' evidence preserves exact Unicode text, source hash and parser')
        downloaded=request('GET','/documents/'+result['id']+'/download',role)
        check(downloaded.content==raw,role+' source download bytes remain unchanged')
    for owner in ('buyer','supplier-desert'):
        for path in ('/record/','/documents/'):
            suffix='' if path=='/record/' else '/evidence'
            request('GET',path+docs[owner]['id']+suffix,'supplier-gulf',404)
        request('GET','/documents/'+docs[owner]['id']+'/download','supplier-gulf',404)
    check(True,'Gulf supplier cannot read another supplier or internal document metadata, evidence or file')
    for suffix in ('','/evidence','/download'):
        path='/record/' if not suffix else '/documents/'
        request('GET',path+docs['buyer']['id']+suffix,'other-buyer',404)
    check(True,'Other tenant cannot read newly uploaded document metadata, evidence or file')
    own=request('GET','/records/document','supplier-gulf').json()['items']
    check(all(x['data'].get('supplier_id')=='gulf' for x in own),'Supplier document collection excludes competitors and internal sources')
    for filename,content,expected_pages in (('invalid.pdf',b'NOT A PDF',[]),('blank.txt',b' \t\n',[' \t\n'])):
        quarantined=request('POST','/documents',status=201,files={'file':(filename,content,'application/octet-stream')}).json()
        detail=request('GET','/record/'+quarantined['id']).json()
        check(detail==quarantined and detail['data']['status']=='quarantined','Quarantined '+filename+' metadata retains its state and error')
        evidence=request('GET','/documents/'+quarantined['id']+'/evidence').json()
        check(evidence['pages']==expected_pages,'Quarantined '+filename+' evidence retains the existing partial-text contract')
        request('GET','/documents/'+quarantined['id']+'/download',status=403)
        check(True,'Quarantined '+filename+' cannot be downloaded')
    search=request('POST','/search',json={'query':marker}).json()
    check(any(hit['document_id']==docs['buyer']['id'] for hit in search['hits']),'Internal search still finds the new parsed source without changing its write path')
    request('POST','/search','supplier-gulf',403,json={'query':marker})
    check(True,'Supplier search access remains restricted')


def job_read_probes(client,check,sql,clone,tokens):
    job_id=sql(clone,"SELECT id FROM proc_document_jobs WHERE tenant='demo' ORDER BY id LIMIT 1")
    saved=sql(clone,"SELECT to_jsonb(j)::text FROM proc_document_jobs j WHERE tenant='demo' AND id='"+job_id+"'")
    where=" WHERE tenant='demo' AND id='"+job_id+"'"
    def restore():
        sql(clone,'DELETE FROM proc_document_jobs'+where)
        sql(clone,"INSERT INTO proc_document_jobs SELECT * FROM jsonb_populate_record(NULL::proc_document_jobs,'"+saved.replace("'","''")+"')")
    paths=('/record/'+job_id,'/records/job')
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        response=client.get('/api/v1/record/'+job_id,headers=tokens[role])
        check(response.status_code==404,role+' cannot read internal processing job')
    try:
        sql(clone,"UPDATE proc_document_jobs SET result=result || '{\"read_extension\":{\"sequence\":[2,1,2],\"note\":\"Unicode — اختبار\"}}'::jsonb,source_snapshot=source_snapshot || '{\"read_metadata\":true}'::jsonb"+where)
        for path in paths:
            response=client.get('/api/v1'+path,headers=tokens['buyer'])
            check(response.status_code==200,'Projected job read succeeds for '+path)
            item=response.json() if path.startswith('/record/') else next(x for x in response.json()['items'] if x['id']==job_id)
            check(item['data']['result']['read_extension']=={'sequence':[2,1,2],'note':'Unicode — اختبار'}
                  and item['data']['read_metadata'] is True,
                  'Job reads consume complete projected result and metadata for '+path)
    finally:restore()
    for corruption in ('stale revision','candidate count','missing projection'):
        try:
            if corruption=='stale revision':sql(clone,'UPDATE proc_document_jobs SET source_revision=source_revision+1'+where)
            elif corruption=='candidate count':sql(clone,'UPDATE proc_document_jobs SET candidate_count=candidate_count+1'+where)
            else:sql(clone,'DELETE FROM proc_document_jobs'+where)
            for path in paths:
                response=client.get('/api/v1'+path,headers=tokens['buyer'])
                check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
                      'Job '+corruption+' fails closed for '+path)
        finally:restore()


def job_workflow(client,password,check,tokens):
    from fastapi.encoders import jsonable_encoder
    from supplypilot.db import Session
    from supplypilot.security import lookup_identity
    from supplypilot.domain import get,view
    text='SYNTHETIC JOB READ TEST ONLY\nSKU: PIPE-DN50\nQuantity: 30\nGrade: ASTM A106 Grade B\nUnicode — اختبار\n'
    for role in ('buyer','supplier-gulf'):
        response=client.post('/api/v1/documents',headers=tokens[role],
            files={'file':('job-read-demo.txt',text.encode('utf-8'),'text/plain')})
        check(response.status_code==201,role+' job fixture upload succeeds')
        document=response.json()
        response=client.get('/api/v1/records/job',headers=tokens['buyer'])
        check(response.status_code==200,'Internal processing job collection remains readable')
        jobs=[x for x in response.json()['items'] if x['data']['document_id']==document['id']]
        check(len(jobs)==1,role+' upload creates exactly one completed processing job')
        job=jobs[0]
        detail=client.get('/api/v1/record/'+job['id'],headers=tokens['buyer'])
        with Session() as db:
            buyer=lookup_identity(db,'buyer',by_username=True)
            expected=jsonable_encoder(view(get(db,buyer,job['id']),buyer))
        check(detail.status_code==200 and detail.json()==job==expected,
              'New job collection, detail and authoritative result agree exactly')
        result=job['data']['result']
        check(result['pages']==[text] and len(result['candidates'])==3,
              'Processing result preserves Unicode source text and three anchored candidates')
        check(all(x['reviewed'] is False and text[x['start']:x['end']]==x['raw'] for x in result['candidates'])
              and 'Human review required' in result['flags'],
              'Read cutover preserves unreviewed candidates, exact text offsets and human-review flags')
        check('candidate_count' not in job['data'] and 'model_version' not in result,
              'Deterministic result retains its existing API shape')
        for denied in ('supplier-gulf','supplier-desert','other-buyer'):
            response=client.get('/api/v1/record/'+job['id'],headers=tokens[denied])
            check(response.status_code==404,denied+' cannot inspect new processing job')
    for role in ('supplier-gulf','supplier-desert','other-buyer'):
        response=client.get('/api/v1/records/job',headers=tokens[role])
        check(response.status_code==200 and response.json()['items']==[] and response.json()['total']==0,
              role+' job collection excludes internal processing results')
    before=client.get('/api/v1/records/job',headers=tokens['buyer']).json()['total']
    response=client.post('/api/v1/documents',headers=tokens['buyer'],
        files={'file':('quarantined-job.pdf',b'NOT A PDF','application/pdf')})
    check(response.status_code==201 and response.json()['data']['status']=='quarantined',
          'Unreadable source remains quarantined')
    after=client.get('/api/v1/records/job',headers=tokens['buyer']).json()['total']
    check(after==before,'Quarantined upload creates no fabricated completed job')
