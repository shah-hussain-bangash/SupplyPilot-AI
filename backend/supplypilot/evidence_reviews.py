"""Source-bound field-review events; extraction and procurement facts stay intact."""
from copy import deepcopy
from sqlalchemy import select
from .db import Record,now
from .domain import get,expected,create,audit,digest,fail


def record_review(db,user,job_id,body):
    # Serialize retries and concurrent review events on their source job.
    job=get(db,user,job_id,'job')
    request_digest=digest(body.model_dump(mode='json'))
    prior=db.scalar(select(Record).where(Record.tenant==user.tenant,Record.kind=='evidence_review',
        Record.data['job_id'].as_string()==job_id,Record.data['author'].as_string()==user.id,
        Record.data['request_key'].as_string()==body.key))
    if prior:
        if prior.data['request_digest']!=request_digest:
            fail('idempotency_conflict','This review key was already used for a different decision')
        return prior
    expected(job,body.expected_job_revision)
    doc=get(db,user,job.data.get('document_id'),'document')
    expected(doc,body.expected_document_revision)
    if doc.data.get('sha256')!=body.source_sha256:
        fail('source_changed','Source hash changed; reopen the evidence before reviewing')
    if doc.data.get('status')!='review_required':
        fail('not_reviewable','Quarantined or unreadable sources cannot receive field reviews',422)
    result=job.data.get('result',{})
    pages=doc.data.get('pages')
    if job.data.get('state')!='completed' or not isinstance(result,dict) or not isinstance(pages,list) or not all(isinstance(p,str) for p in pages) or result.get('pages')!=pages:
        fail('source_changed','The processing text does not match the current source; reopen the evidence')
    candidates=result.get('candidates')
    if not isinstance(candidates,list) or body.candidate_index>=len(candidates):
        fail('invalid_candidate','Choose an existing extracted field',422)
    candidate=candidates[body.candidate_index]
    if not isinstance(candidate,dict):fail('invalid_candidate','Extracted field is incomplete',422)
    page=candidate.get('page');start=candidate.get('start');end=candidate.get('end')
    raw=candidate.get('raw');normalized=candidate.get('normalized');field=candidate.get('field')
    if not all(type(v) is int for v in (page,start,end)) or not 1<=page<=len(pages) or \
       not 0<=start<end<=len(pages[page-1]) or not isinstance(raw,str) or \
       pages[page-1][start:end]!=raw or not isinstance(normalized,str) or \
       not isinstance(field,str) or not field:
        fail('invalid_anchor','The extracted field has no exact source anchor; manual source handling is required',422)
    value=body.corrected_value if body.decision=='corrected' else normalized if body.decision=='accepted' else None
    event=create(db,user,'evidence_review',{
        'job_id':job.id,'job_revision':job.revision,'document_id':doc.id,
        'document_revision':doc.revision,'source_sha256':doc.data['sha256'],
        'candidate_index':body.candidate_index,'candidate_snapshot':deepcopy(candidate),
        'field':field,'decision':body.decision,'reviewed_value':value,'reason':body.reason,
        'author':user.id,'author_username':user.username,'recorded_at':now(),
        'request_key':body.key,'request_digest':request_digest,'training_use':False,
        'scope':'Extraction field review only; not supplier, certificate or purchase approval'})
    audit(db,user,'evidence_review.recorded',event.id,{'job_id':job.id,
        'document_id':doc.id,'candidate_index':body.candidate_index,'decision':body.decision})
    return event
