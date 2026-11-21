"""Explicit baseline migration and local-only synthetic seed."""
import argparse
import hashlib
import os
from datetime import date, timedelta
from sqlalchemy import select, text
from . import config
from .db import Base, engine, Session, User, Record, now, bind_tenant
from .security import password_hash

def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(text('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)'))
        if not db.scalar(text('SELECT version FROM schema_version LIMIT 1')):
            db.execute(text('INSERT INTO schema_version VALUES (1)'))
    print('Schema baseline 001 applied (idempotent; use reviewed versioned migrations for future changes).')

def seed():
    if config.MODE!='local':raise RuntimeError('Synthetic seed is local-only')
    password=os.getenv('DEMO_PASSWORD','')
    if len(password)<12:raise RuntimeError('Set DEMO_PASSWORD to at least 12 characters before seeding.')
    with Session.begin() as db:
        bind_tenant(db,'demo')
        if db.get(User,'buyer'):
            print('Seed already exists; existing credentials and data preserved.');return
        for role in ('buyer','technical','manager','warehouse','finance','planner','auditor','admin'):
            db.add(User(id=role,username=role,tenant='demo',role=role,password_hash=password_hash(password),authority_cents=2_000_000 if role=='manager' else 0))
        for i in ('gulf','desert','budget'):
            db.add(User(id='supplier-'+i,username='supplier-'+i,tenant='demo',role='supplier',supplier_id=i,password_hash=password_hash(password)))
        pages=['Marina utilities upgrade\nSKU: PIPE-DN50\nQuantity: 100\nGrade: ASTM A106 Grade B\nStandard: DN50 Schedule 40 seamless\nSYNTHETIC DEMONSTRATION DATA - NOT A REAL CERTIFICATE']
        raw=pages[0].encode();(config.DATA/'documents').mkdir(exist_ok=True)
        (config.DATA/'documents'/'source-demo').write_bytes(raw)
        db.add(Record(id='source-demo',tenant='demo',kind='document',data={'filename':'synthetic-rfq-and-certificate.txt','sha256':hashlib.sha256(raw).hexdigest(),'status':'review_required','pages':pages,'supplier_id':None,'parser':'synthetic-seed','malware_scanned':False}))
        specs={'grade':'ASTM A106 Grade B','size':'DN50','schedule':'40','construction':'seamless'}
        today=date.today()
        due=(today+timedelta(days=7)).isoformat()
        db.add(Record(id='rfq-demo',tenant='demo',kind='rfq',data={'title':'Marina utilities upgrade - synthetic','due_date':due,'owner':'buyer','status':'validated','reviewer':'technical','invited':['gulf','desert','budget'],'lines':[{'sku':'PIPE-DN50','quantity':100,'unit':'piece','specs':specs,'evidence_id':'source-demo'}]}))
        db.add(Record(id='stock-demo',tenant='demo',kind='stock',data={'sku':'PIPE-DN50','usable':35,'reserved':10,'quarantine':0,'inbound':[{'quantity':20,'confirmed':True,'date':(today+timedelta(days=2)).isoformat()}],'as_of':now(),'source':'local-simulator'}))
        for sid,name,qty,price,freight,days in [('gulf','Gulf Industrial',30,'120.00','5.00',3),('desert','Desert Engineering',40,'128.00','12.00',4),('budget','Budget Metals',55,'108.00','0.00',3)]:
            db.add(Record(id=sid,tenant='demo',kind='supplier',data={'name':name,'approved':True,'category':'Industrial pipe','simulated':True}))
            db.add(Record(id='offer-'+sid,tenant='demo',kind='offer',data={'rfq_id':'rfq-demo','supplier_id':sid,'sku':'PIPE-DN50','quantity':qty,'unit':'piece','unit_price':price,'freight_per_piece':freight,'currency':'AED','valid_until':due,'delivery_date':(today+timedelta(days=days)).isoformat(),'specs':specs,'evidence_id':'source-demo','recipient':sid+'@example.invalid','terms':'Synthetic net 30; no real dispatch','compliance':{'status':'unknown'},'compliance_revision':None,'status':'submitted'}))
    with Session.begin() as db:
        bind_tenant(db,'other')
        if not db.get(User,'other-buyer'):
            db.add(User(id='other-buyer',username='other-buyer',tenant='other',role='buyer',password_hash=password_hash(password)))
    print('Synthetic seed ready. Accounts: buyer, technical, manager, warehouse, finance, planner, auditor, admin, supplier-gulf, supplier-desert, supplier-budget. Password is the supplied DEMO_PASSWORD.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['migrate','seed','openapi']);args=parser.parse_args()
    if args.command=='migrate':migrate()
    elif args.command=='seed':seed()
    else:
        import json
        from .main import app
        print(json.dumps(app.openapi(),indent=2))

if __name__=='__main__':main()
