import os
import tempfile
from pathlib import Path
import pytest

TEST_DIR=Path(tempfile.mkdtemp(prefix='supplypilot-test-'))
os.environ.update(DATA_DIR=str(TEST_DIR),DATABASE_URL='sqlite:///'+(TEST_DIR/'test.db').as_posix(),APP_MODE='local',AUTH_MODE='local',DEMO_PASSWORD='Test-only-password-2026',TOKEN_SECRET='test-secret-is-not-a-deployment-secret-123456789')
from supplypilot.db import Base,engine,Session,User
from supplypilot.security import token_for,password_hash
from supplypilot import manage
from supplypilot.main import app,login_attempts
from fastapi.testclient import TestClient

CACHED_HASH=password_hash(os.environ['DEMO_PASSWORD'])

@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    provider=TEST_DIR/'erp-simulator.db'
    if provider.exists():provider.unlink()
    monkeypatch.setattr(manage,'password_hash',lambda _:CACHED_HASH)
    manage.seed();login_attempts.clear()
    with TestClient(app) as c:yield c

@pytest.fixture
def headers():
    def h(role):
        with Session() as db:return {'Authorization':'Bearer '+token_for(db.get(User,role))}
    return h

@pytest.fixture
def api(client,headers):
    class API:
        def get(self,path,role='buyer'):
            r=client.get('/api/v1'+path,headers=headers(role));assert r.status_code==200,r.text;return r.json()
        def post(self,path,data,role='buyer',status=200):
            r=client.post('/api/v1'+path,json=data,headers=headers(role));assert r.status_code==status,r.text;return r.json()
        def ready(self):
            for sid in ('gulf','desert'):
                self.post('/offers/offer-'+sid+'/assess',{'expected_revision':1,'certificate_verified':True,'reason':'Synthetic certificate checked'},'technical')
            return self.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000.00'},status=201)
        def order(self,timeout=False):
            p=self.ready();p=self.post('/plans/'+p['id']+'/decision',{'expected_revision':p['revision'],'decision':'approved','reason':'Within demo budget and reviewed'},'manager')
            intent=self.post('/plans/'+p['id']+'/execute',{'expected_revision':p['revision'],'key':'test-order-key-0001'},status=202)
            self.post('/executions/'+intent['id']+'/dispatch',{'simulate_timeout':timeout})
            if timeout:self.post('/executions/'+intent['id']+'/reconcile',{})
            return self.get('/records/order')['items'][0]
    return API()
