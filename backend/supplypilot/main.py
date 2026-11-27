import hashlib
import io
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from . import config, schemas as S, procurement as P
from .db import Session, User, Record, Audit, Outbox, get_db, now
from .security import actor, allow, password_ok, token_for, profile, lookup_identity
from .domain import create, get, records, save, view, fail, evidence, audit
from .intelligence import extraction_graph, search_pages, backtest
from .integrations import intent_view, get_intent, process
from .planning import money
from . import relational_reads

# Finish the shared request transaction before acknowledging the response.
# Authentication and endpoints use the same function-scoped cached dependency.
log=logging.getLogger('supplypilot')
login_attempts=defaultdict(deque)

@asynccontextmanager
async def lifespan(app):
    # Explicit migration command owns schema creation; startup never seeds demo data.
    with Session() as db:db.execute(text('SELECT 1'))
    yield

app=FastAPI(title='SupplyPilot AI',version='0.1.0',lifespan=lifespan,description='Runnable local reference. ERP is simulated; advanced production gates remain open.')

@app.middleware('http')
async def request_context(request:Request,call_next):
    rid=str(uuid4());start=time.monotonic()
    response=await call_next(request)
    response.headers['X-Request-ID']=rid
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    log.info(json.dumps({'request_id':rid,'method':request.method,'path':request.url.path,'status':response.status_code,'duration_ms':round((time.monotonic()-start)*1000,2)}))
    return response

@app.exception_handler(IntegrityError)
async def conflict(_,exc):return JSONResponse(status_code=409,content={'detail':{'code':'integrity_conflict','message':'Duplicate or conflicting write; reload before retry'}})

@app.exception_handler(OperationalError)
async def dependency_error(_,exc):return JSONResponse(status_code=503,content={'detail':{'code':'database_unavailable','message':'Database unavailable or busy; retry reads, reconcile writes'}})

@app.get('/health')
def health(db=Depends(get_db,scope='function')):
    db.execute(text('SELECT 1'))
    return {'status':'ok','version':'0.1.0','mode':config.MODE,'erp':'local-simulator','ai':'rule extraction + lexical retrieval + baseline forecast','auth':config.AUTH_MODE}

@app.post('/api/v1/auth/login')
def login(body:S.Login,request:Request,db=Depends(get_db,scope='function')):
    if config.AUTH_MODE!='local':fail('oidc_required','Use your identity provider access token',403)
    key=request.client.host if request.client else 'unknown';q=login_attempts[key];t=time.monotonic()
    while q and t-q[0]>60:q.popleft()
    if len(q)>=20:raise HTTPException(429,'Too many login attempts; wait one minute')
    q.append(t)
    user=lookup_identity(db,body.username,by_username=True)
    if not user or not password_ok(body.password,user.password_hash):raise HTTPException(401,'Invalid credentials')
    return {'access_token':token_for(user),'token_type':'bearer','user':profile(user)}

@app.get('/api/v1/me')
def me(user=Depends(actor)):return profile(user)

KINDS={'rfq','supplier','stock','offer','plan','order','receipt','invoice','exception','document','job','feedback','evaluation','customer_quote'}

@app.get('/api/v1/records/{kind}')
def collection(kind:str,offset:int=0,limit:int=100,user=Depends(actor),db=Depends(get_db,scope='function')):
    if kind not in KINDS:fail('not_found','Collection unavailable',404)
    if offset<0 or not 1<=limit<=200:fail('pagination','Invalid page bounds',422)
    projected=relational_reads.collection(db,user,kind,offset,limit)
    if projected is not None:return projected
    rows=records(db,user,kind)
    return {'items':[view(r,user) for r in rows[offset:offset+limit]],'total':len(rows),'offset':offset,'limit':limit}

@app.get('/api/v1/record/{rid}')
def record(rid:str,user=Depends(actor),db=Depends(get_db,scope='function')):
    projected=relational_reads.record(db,user,rid)
    if projected is not None:return projected
    return view(get(db,user,rid),user)

@app.post('/api/v1/rfqs',status_code=201)
def new_rfq(body:S.RFQCreate,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer');d=body.model_dump(mode='json');d.update(status='draft',owner=user.id,invited=[])
    for line in d['lines']:
        if line['evidence_id']:evidence(db,user,line['evidence_id'])
    return view(create(db,user,'rfq',d))

@app.post('/api/v1/rfqs/{rid}/review')
def review(rid:str,body:S.RFQReview,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.review_rfq(db,user,rid,body))

@app.post('/api/v1/rfqs/{rid}/invite')
def invitation(rid:str,body:S.Invite,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.invite(db,user,rid,body))

@app.post('/api/v1/offers',status_code=201)
def offer(body:S.OfferCreate,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.offer(db,user,body),user)

@app.post('/api/v1/offers/{rid}/assess')
def assess(rid:str,body:S.Compliance,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.assess(db,user,rid,body))

@app.post('/api/v1/plans',status_code=201)
def planning(body:S.PlanCreate,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.make_plan(db,user,body))

@app.post('/api/v1/stock/{rid}/refresh-simulator')
def refresh_stock(rid:str,body:S.Mutation,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'planner')
    if config.MODE!='local':fail('local_only','Live stock synchronization is not configured',403)
    r=get(db,user,rid,'stock');d=deepcopy(r.data);d['as_of']=now()
    return view(save(db,user,r,body.expected_revision,d,'simulator.stock_timestamp_refreshed'))

@app.post('/api/v1/plans/{rid}/decision')
def decision(rid:str,body:S.Decision,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.decide(db,user,rid,body))

@app.post('/api/v1/plans/{rid}/execute',status_code=202)
def execute(rid:str,body:S.Execute,user=Depends(actor),db=Depends(get_db,scope='function')):return intent_view(P.execute(db,user,rid,body))

@app.get('/api/v1/executions')
def executions(user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','manager','auditor')
    return [intent_view(r) for r in db.scalars(select(Outbox).where(Outbox.tenant==user.tenant).order_by(Outbox.created_at.desc()))]

@app.post('/api/v1/executions/{iid}/dispatch')
def dispatch(iid:str,body:S.Dispatch,user=Depends(actor)):
    allow(user,'buyer')
    if config.MODE!='local' and body.simulate_timeout:fail('local_only','Fault simulation is local-only',403)
    return process(iid,user.tenant,user.id,body.simulate_timeout)

@app.post('/api/v1/executions/{iid}/cancel-pending')
def cancel_pending(iid:str,body:S.Mutation,user=Depends(actor),db=Depends(get_db,scope='function')):
    return intent_view(P.cancel_pending(db,user,iid,body))

@app.post('/api/v1/executions/{iid}/reconcile')
def reconcile(iid:str,user=Depends(actor)):
    allow(user,'buyer');return process(iid,user.tenant,user.id,reconcile_only=True)

@app.post('/api/v1/receipts',status_code=201)
def receipt(body:S.Receipt,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.receive(db,user,body))

@app.post('/api/v1/invoices/{rid}/recheck')
def recheck_invoice(rid:str,body:S.InvoiceRecheck,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.recheck_invoice(db,user,rid,body))

@app.post('/api/v1/invoices',status_code=201)
def invoice(body:S.Invoice,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.invoice(db,user,body))

@app.post('/api/v1/orders/{rid}/close')
def close(rid:str,body:S.Mutation,user=Depends(actor),db=Depends(get_db,scope='function')):return view(P.close(db,user,rid,body))

@app.post('/api/v1/documents',status_code=201)
async def upload(file:UploadFile=File(...),user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','technical','supplier','warehouse','finance')
    raw=await file.read(config.MAX_UPLOAD+1)
    if len(raw)>config.MAX_UPLOAD:fail('upload_too_large','Maximum upload is 5 MiB',413)
    filename=Path(file.filename or 'source').name;ext=Path(filename).suffix.lower()
    if ext not in ('.pdf','.txt','.csv','.json'):fail('unsupported_file','Use PDF, TXT, CSV or JSON; images and Office OCR are deferred',422)
    pages=[];status='review_required';error=None
    try:
        if ext=='.pdf':
            if not raw.startswith(b'%PDF-'):raise ValueError('Invalid PDF signature')
            reader=PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages)>60:raise ValueError('Encrypted PDFs or documents over 60 pages are not supported')
            pages=[(p.extract_text() or '')[:20000] for p in reader.pages]
        else:pages=[raw.decode('utf-8')[:200000]]
        if not any(p.strip() for p in pages):raise ValueError('No text found; scanned sources require OCR and manual processing')
    except Exception:
        status='quarantined';error='Unable to safely parse supported text; manual review required'
    doc=create(db,user,'document',{'filename':filename,'sha256':hashlib.sha256(raw).hexdigest(),'status':status,'error':error,'pages':pages,'supplier_id':user.supplier_id,'parser':'pypdf/text-v1','malware_scanned':False})
    (config.DATA/'documents').mkdir(exist_ok=True)
    (config.DATA/'documents'/doc.id).write_bytes(raw)
    if status=='review_required':
        result=extraction_graph.invoke({'pages':pages,'candidates':[],'flags':[]})
        create(db,user,'job',{'document_id':doc.id,'state':'completed','execution':'synchronous-bounded-graph','result':result})
    audit(db,user,'document.ingested',doc.id,{'status':status,'sha256':doc.data['sha256']})
    return view(doc,user)

@app.get('/api/v1/documents/{rid}/evidence')
def doc_evidence(rid:str,user=Depends(actor),db=Depends(get_db,scope='function')):
    projected=relational_reads.document_evidence(db,user,rid)
    if projected is not None:return projected
    d=get(db,user,rid,'document')
    return {'document_id':d.id,'sha256':d.data['sha256'],'pages':d.data.get('pages',[]),'parser':d.data['parser']}

@app.post('/api/v1/documents/{rid}/model-extract')
def model_extract(rid:str,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','technical')
    from .model_gateway import extract_with_gateway
    d=evidence(db,user,rid);result=extract_with_gateway(d.data['pages'])
    audit(db,user,'model.extraction_requested',rid,{'model_version':result['model_version'],'source_sha256':d.data['sha256']})
    return view(create(db,user,'job',{'document_id':rid,'state':'completed','execution':'private-model-gateway','result':result}))

@app.get('/api/v1/documents/{rid}/download')
def download(rid:str,user=Depends(actor),db=Depends(get_db,scope='function')):
    d=get(db,user,rid,'document')
    if d.data['status']=='quarantined':fail('quarantined','Quarantined documents cannot be downloaded through this endpoint',403)
    path=config.DATA/'documents'/d.id
    if not path.is_file():fail('not_found','Source blob unavailable',404)
    audit(db,user,'document.downloaded',rid)
    return FileResponse(path,filename=d.data['filename'],media_type='application/octet-stream')

@app.post('/api/v1/search')
def search(body:S.Search,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','technical','manager','planner','auditor')
    hits=search_pages([d for d in records(db,user,'document') if d.data['status']=='review_required'],body.query)
    return {'method':'lexical-baseline','answer':None,'abstained':not bool(hits),'hits':hits,'note':'Quoted evidence only. Semantic embeddings, reranking and generated answers are not enabled.'}

@app.post('/api/v1/exceptions',status_code=201)
def issue(body:S.ExceptionCreate,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','technical','manager','warehouse','finance','planner');get(db,user,body.resource_id)
    owner=db.get(User,body.owner)
    if not owner or owner.tenant!=user.tenant or owner.role=='supplier':fail('invalid_owner','Choose an internal owner in this tenant',422)
    prior=next((r for r in records(db,user,'exception') if r.data['resource_id']==body.resource_id and r.data['category']==body.category and r.data['status']=='open'),None)
    if prior:return view(prior)
    return view(create(db,user,'exception',{**body.model_dump(mode='json'),'status':'open'}))

@app.post('/api/v1/exceptions/{rid}/resolve')
def resolve(rid:str,body:S.Resolve,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','technical','manager','warehouse','finance','planner');r=get(db,user,rid,'exception')
    if user.id!=r.data['owner'] and user.role!='manager':fail('not_owner','Only assigned owner or manager may resolve',403)
    evidence(db,user,body.evidence_id)
    if r.data['status']!='open':fail('invalid_state','Case is not open')
    d=deepcopy(r.data);d.update(status='resolved',resolution=body.reason,evidence_id=body.evidence_id,resolved_by=user.id)
    return view(save(db,user,r,body.expected_revision,d,'exception.resolved'))

@app.post('/api/v1/exceptions/{rid}/reopen')
def reopen(rid:str,body:S.Mutation,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'manager');r=get(db,user,rid,'exception');d=deepcopy(r.data);d['status']='open'
    return view(save(db,user,r,body.expected_revision,d,'exception.reopened'))

@app.post('/api/v1/forecast')
def forecast(body:S.Forecast,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'planner','buyer');result=backtest(body.values)
    return view(create(db,user,'evaluation',{'type':'synthetic-user-series-baseline','values':body.values,'result':result,'release_gate_passed':False}))

@app.post('/api/v1/customer-quotes',status_code=201)
def customer_quote(body:S.Quote,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer');p=get(db,user,body.plan_id,'plan')
    net=money(body.selling_price)-money(body.discount);cost=money(p.data['payload']['total'])
    if net<=0:fail('invalid_price','Net selling price must be positive',422)
    contribution=net-cost
    return view(create(db,user,'customer_quote',{'plan_id':p.id,'net':str(net),'cost':str(cost),'contribution':str(contribution),'margin_pct':str((contribution/net*100).quantize(Decimal('0.01'))),'status':'draft_requires_commercial_review','sent':False,'note':'Material/freight scenario only; excludes tax, overhead and other owner-defined charges'}))

@app.post('/api/v1/feedback',status_code=201)
def feedback(body:S.Feedback,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','technical','manager','planner','warehouse','finance');get(db,user,body.resource_id)
    return view(create(db,user,'feedback',{**body.model_dump(),'status':'pending','author':user.id,'training_use':False}))

@app.post('/api/v1/feedback/{rid}/adjudicate')
def adjudicate(rid:str,body:S.Decision,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'technical');r=get(db,user,rid,'feedback')
    if r.data['status']!='pending':fail('invalid_state','Feedback already adjudicated')
    d=deepcopy(r.data);d.update(status=body.decision,reason=body.reason,reviewer=user.id)
    return view(save(db,user,r,body.expected_revision,d,'feedback.adjudicated'))

@app.get('/api/v1/analytics')
def analytics(user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'buyer','manager','planner','finance','auditor')
    orders=records(db,user,'order');closed=[o for o in orders if o.data['status']=='closed']
    return {'data_label':'LOCAL SIMULATION / user-entered records - not measured business savings','order_count':len(orders),'closed_count':len(closed),'open_exception_count':sum(x.data['status']=='open' for x in records(db,user,'exception')),'simulated_material_commitment':str(sum((money(o.data['total']) for o in orders),Decimal('0'))),'currency':'AED','definition':'Sum of simulator order payload totals, including open orders; not savings or paid spend','realized_savings':None}

@app.get('/api/v1/audit')
def audit_list(offset:int=0,limit:int=100,user=Depends(actor),db=Depends(get_db,scope='function')):
    allow(user,'auditor','manager')
    if offset<0 or not 1<=limit<=200:fail('pagination','Invalid bounds',422)
    rows=db.scalars(select(Audit).where(Audit.tenant==user.tenant).order_by(Audit.at.desc()).offset(offset).limit(limit))
    return [{'id':r.id,'actor':r.actor,'action':r.action,'resource':r.resource,'details':r.details,'at':r.at} for r in rows]

web=Path(__file__).resolve().parents[2]/'frontend'/'dist'
if web.is_dir():app.mount('/',StaticFiles(directory=web,html=True),name='web')
