"""Customer-quote API probes for the runner-owned disposable database only."""
import json
from uuid import uuid4


def quote_workflow(client,check,tokens,plan_id):
    for selling,discount in (('10000.00','200.00'),('1000.00','0.00')):
        body={'plan_id':plan_id,'selling_price':selling,'discount':discount}
        response=client.post('/api/v1/customer-quotes',headers=tokens['buyer'],json=body)
        check(response.status_code==201,'Buyer creates a synthetic commercial draft')
        quote=response.json()
        for role in ('buyer','manager','finance','auditor','warehouse'):
            detail=client.get('/api/v1/record/'+quote['id'],headers=tokens[role])
            page=client.get('/api/v1/records/customer_quote',headers=tokens[role])
            if detail.status_code!=200 or page.status_code!=200 or detail.json()!=quote:
                raise AssertionError(f'Quote read parity: created={quote!r}, detail={detail.status_code} {detail.text}, page={page.status_code} {page.text[:1500]}')
            check(detail.status_code==200 and page.status_code==200 and
                  detail.json()==quote==next(x for x in page.json()['items'] if x['id']==quote['id']),
                  role+' quote creation, detail and collection preserve the exact financial snapshot')
        check(quote['data']['status']=='draft_requires_commercial_review' and quote['data']['sent'] is False,
              'Relational reads do not imply commercial approval or sending')
        for role in ('supplier-gulf','supplier-desert','other-buyer'):
            detail=client.get('/api/v1/record/'+quote['id'],headers=tokens[role])
            page=client.get('/api/v1/records/customer_quote',headers=tokens[role])
            check(detail.status_code==404 and page.status_code==200 and page.json()['total']==0,
                  role+' cannot read internal customer quotes')
        for role in ('finance','supplier-gulf','other-buyer'):
            denied=client.post('/api/v1/customer-quotes',headers=tokens[role],json=body)
            check(denied.status_code in (403,404),role+' cannot create a quote against the demo plan')


def quote_read_probes(client,check,sql,clone,tokens):
    if clone!='supplypilot_dev':raise ValueError('Unexpected disposable runner database')
    identity='quote-read-'+uuid4().hex
    plan=sql(clone,"SELECT id FROM proc_plans WHERE tenant='demo' ORDER BY id LIMIT 1")
    snapshot=dict(plan_id=plan,net='32.00',cost='31.00',contribution='1.00',margin_pct='3.12',
        status='draft_requires_commercial_review',sent=False,note='Synthetic — اختبار',
        extension={'sequence':[2,1,2]},history=[{'note':'preserve me'}])
    encoded=json.dumps(snapshot,ensure_ascii=False).replace("'","''")
    sql(clone,"INSERT INTO records(id,tenant,kind,revision,data,created_at,updated_at) VALUES ('"+
        identity+"','demo','customer_quote',1,'"+encoded+"','2030-01-01','2030-01-01')")
    where=" WHERE tenant='demo' AND id='"+identity+"'"
    saved=sql(clone,'SELECT to_jsonb(q)::text FROM proc_customer_quotes q'+where)
    def restore():
        sql(clone,'DELETE FROM proc_customer_quotes'+where)
        sql(clone,"INSERT INTO proc_customer_quotes SELECT * FROM jsonb_populate_record(NULL::proc_customer_quotes,'"+
            saved.replace("'","''")+"')")
    paths=('/record/'+identity,'/records/customer_quote')
    def item(path):
        response=client.get('/api/v1'+path,headers=tokens['buyer'])
        check(response.status_code==200,'Quote projected response succeeds for '+path)
        return response.json() if path.startswith('/record/') else next(x for x in response.json()['items'] if x['id']==identity)
    try:
        for path in paths:
            check(item(path)['data']==snapshot,'Half-even margin, Unicode, history and decimal strings remain exact for '+path)
        for body in (
            dict(snapshot,net='00100.0',cost='000.00',contribution='100',margin_pct='100.0'),
            dict(snapshot,net='1000.00',cost='7250.00',contribution='-6250.00',margin_pct='-625.00')):
            sql(clone,"UPDATE records SET revision=revision+1,data='"+json.dumps(body).replace("'","''")+"'"+where)
            for path in paths:check(item(path)['data']==body,'Zero-cost or negative-margin snapshot reads without reformatting for '+path)
        sql(clone,"UPDATE records SET revision=revision+1,data='"+encoded+"'"+where)
        saved=sql(clone,'SELECT to_jsonb(q)::text FROM proc_customer_quotes q'+where)
        sql(clone,"UPDATE proc_customer_quotes SET note='Projected commercial note',source_snapshot=source_snapshot || "
            "'{\"read_extension\":true}'::jsonb"+where)
        for path in paths:
            data=item(path)['data']
            check(data['note']=='Projected commercial note' and data['read_extension'] is True,
                  'Quote reads use normalized metadata and projected extensions for '+path)
        restore()
        for corruption in ('stale revision','amount disagreement','incomplete snapshot','missing projection'):
            try:
                if corruption=='stale revision':sql(clone,'UPDATE proc_customer_quotes SET source_revision=source_revision+1'+where)
                elif corruption=='amount disagreement':sql(clone,"UPDATE proc_customer_quotes SET source_snapshot=jsonb_set(source_snapshot,'{net}','\"33.00\"'::jsonb)"+where)
                elif corruption=='incomplete snapshot':sql(clone,"UPDATE proc_customer_quotes SET source_snapshot=source_snapshot-'margin_pct'"+where)
                else:sql(clone,'DELETE FROM proc_customer_quotes'+where)
                for path in paths:
                    response=client.get('/api/v1'+path,headers=tokens['buyer'])
                    check(response.status_code==503 and response.json()['detail']['code']=='projection_not_ready',
                          'Quote '+corruption+' fails closed for '+path)
                for role in ('supplier-gulf','other-buyer'):
                    response=client.get('/api/v1/record/'+identity,headers=tokens[role])
                    check(response.status_code==404,role+' cannot infer quote projection health')
            finally:restore()
    finally:
        sql(clone,'DELETE FROM records'+where)
