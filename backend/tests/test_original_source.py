import hashlib
import pytest
from sqlalchemy import select,func
from supplypilot import config
from supplypilot.db import Session,Record,Audit,TenantSession


def source(client,headers,role='buyer'):
    raw='📦 SYNTHETIC SOURCE ONLY\nSKU: PIPE-DN50\nQuantity: 30\n'.encode()
    response=client.post('/api/v1/documents',headers=headers(role),
        files={'file':('原本-demo.txt',raw,'text/plain')})
    assert response.status_code==201,response.text
    return response.json(),raw


def path(doc):
    return '/api/v1/documents/'+doc['id']+'/download'


def binding(doc):
    return {'expected_revision':doc['revision'],'expected_sha256':doc['data']['sha256']}


def test_original_bytes_hash_revision_attachment_and_audit(client,headers):
    doc,raw=source(client,headers)
    response=client.get(path(doc),params=binding(doc),headers=headers('technical'))
    assert response.status_code==200 and response.content==raw
    assert response.headers['X-SupplyPilot-Source-SHA256']==hashlib.sha256(raw).hexdigest()
    assert response.headers['X-SupplyPilot-Source-Revision']==str(doc['revision'])
    assert response.headers['Content-Disposition'].startswith("attachment; filename*=utf-8''%")
    assert response.headers['Content-Type']=='application/octet-stream'
    assert response.headers['Cache-Control']=='no-store' and response.headers['X-Content-Type-Options']=='nosniff'
    audit=client.get('/api/v1/audit',headers=headers('auditor')).json()
    event=next(a for a in audit if a['resource']==doc['id'] and a['action']=='document.downloaded')
    assert event['details']=={'source_sha256':doc['data']['sha256'],'source_revision':doc['revision']}


@pytest.mark.parametrize('change,status',[
    ({'expected_revision':99},409),({'expected_sha256':'0'*64},409),
    ({'expected_revision':0},422),({'expected_sha256':'invalid'},422)])
def test_stale_or_invalid_binding_sends_no_file_and_no_download_audit(client,headers,change,status):
    doc,_=source(client,headers);params=binding(doc);params.update(change)
    response=client.get(path(doc),params=params,headers=headers('buyer'))
    assert response.status_code==status and 'Content-Disposition' not in response.headers
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='document.downloaded'))==0


@pytest.mark.parametrize('damage,status',[('tampered',503),('missing',404),('oversized',413),('quarantine',403)])
def test_unreliable_original_cannot_be_downloaded(client,headers,damage,status):
    doc,_=source(client,headers);blob=config.DATA/'documents'/doc['id']
    if damage=='tampered':blob.write_bytes(b'TAMPERED SYNTHETIC FIXTURE')
    elif damage=='missing':blob.unlink()
    elif damage=='oversized':blob.write_bytes(b'x'*(5*1024*1024+1))
    else:
        with Session.begin() as db:
            row=db.get(Record,doc['id']);row.data=dict(row.data,status='quarantined')
    response=client.get(path(doc),params=binding(doc),headers=headers('buyer'))
    assert response.status_code==status and 'Content-Disposition' not in response.headers


def test_supplier_and_tenant_boundaries_are_preserved(client,headers):
    doc,raw=source(client,headers,'supplier-gulf')
    assert client.get(path(doc),params=binding(doc),headers=headers('supplier-gulf')).content==raw
    for role in ('supplier-desert','other-buyer'):
        response=client.get(path(doc),params=binding(doc),headers=headers(role))
        assert response.status_code==404 and 'Content-Disposition' not in response.headers


def test_download_audit_commit_failure_prevents_http_success(client,headers,monkeypatch):
    from sqlalchemy.exc import OperationalError
    doc,_=source(client,headers)
    def fail_commit(db):raise OperationalError('synthetic failure',None,Exception('test only'))
    with monkeypatch.context() as patch:
        patch.setattr(TenantSession,'commit',fail_commit)
        response=client.get(path(doc),params=binding(doc),headers=headers('buyer'))
    assert response.status_code==503 and 'Content-Disposition' not in response.headers
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='document.downloaded'))==0
