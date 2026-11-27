"""A successful HTTP acknowledgement must mean the transaction is committed."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError,OperationalError
from supplypilot.db import TenantSession,Session,Record,Audit
from supplypilot.main import app


def observe_response_start(events):
    async def observed(scope,receive,send):
        async def observed_send(message):
            if message['type']=='http.response.start':
                events.append(('response',message['status']))
            await send(message)
        await app(scope,receive,observed_send)
    return observed


def test_commit_finishes_before_http_success_is_sent(client,headers,monkeypatch):
    events=[]
    commit=TenantSession.commit
    def tracked_commit(db):
        commit(db)
        events.append(('commit',None))
    monkeypatch.setattr(TenantSession,'commit',tracked_commit)
    with TestClient(observe_response_start(events)) as probe:
        response=probe.post('/api/v1/feedback',headers=headers('buyer'),
            json={'resource_id':'rfq-demo','correction':'Synthetic response boundary regression'})
    assert response.status_code==201
    assert events.index(('commit',None))<events.index(('response',201))
    with Session() as db:
        assert db.get(Record,response.json()['id']) is not None


@pytest.mark.parametrize('exception,status,code',[
    (IntegrityError,409,'integrity_conflict'),
    (OperationalError,503,'database_unavailable')])
def test_commit_failure_returns_error_and_rolls_back_source_and_audit(client,headers,monkeypatch,exception,status,code):
    events=[]
    def failed_commit(db):
        raise exception('synthetic commit failure',None,Exception('test-only database failure'))
    monkeypatch.setattr(TenantSession,'commit',failed_commit)
    with TestClient(observe_response_start(events)) as probe:
        response=probe.post('/api/v1/feedback',headers=headers('buyer'),
            json={'resource_id':'rfq-demo','correction':'Synthetic failing transaction regression'})
    assert response.status_code==status
    assert response.json()['detail']['code']==code
    assert events==[('response',status)]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Record).where(Record.kind=='feedback'))==0
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='feedback.created'))==0
