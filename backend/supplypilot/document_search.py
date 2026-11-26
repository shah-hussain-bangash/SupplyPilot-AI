"""Bounded lexical evidence retrieval, without generated answers or external calls."""
from collections import Counter
import re
from sqlalchemy import select
from .db import Record
from .domain import fail
from .security import allow
from . import relational_reads

MAX_DOCUMENTS=200
MAX_CHARACTERS=2_000_000
PASSAGE_CHARACTERS=650
MAX_HITS=8


def query_terms(query):
    terms={match.group().casefold() for match in re.finditer(r'\w+',query)}
    if not terms or len(terms)>32:
        fail('invalid_search','Use between one and 32 words or identifiers',422)
    return terms


def _passage(text,terms):
    # Match original tokens, then case-fold their values. Offsets always refer
    # to the original Python string, including Unicode case-fold expansions.
    matches=[(m.start(),m.end(),m.group().casefold()) for m in re.finditer(r'\w+',text)
             if m.group().casefold() in terms]
    counts=Counter();left=0;best=None
    for right,(_,end,term) in enumerate(matches):
        counts[term]+=1
        while len(counts)==len(terms):
            start=matches[left][0]
            if end-start<=PASSAGE_CHARACTERS:
                candidate=(end-start,start,end)
                if best is None or candidate<best:best=candidate
            old=matches[left][2];counts[old]-=1
            if not counts[old]:del counts[old]
            left+=1
    if best is None:return None
    width,start,end=best
    quote_start=max(0,start-100)
    quote_end=min(len(text),quote_start+PASSAGE_CHARACTERS)
    if quote_end<end:quote_start=end-PASSAGE_CHARACTERS;quote_end=end
    return {'start':quote_start,'end':quote_end,'quote':text[quote_start:quote_end],
            'match_spans':[{'start':a,'end':b,'term':term} for a,b,term in matches
                           if a>=quote_start and b<=quote_end],'match_width':width}


def search_pages(documents,query):
    terms=query_terms(query);hits=[];characters=0
    for index,doc in enumerate(documents):
        if index>=MAX_DOCUMENTS:
            fail('search_scope_limit','This local search supports up to 200 authorized documents',413)
        if doc.data.get('status')!='review_required':continue
        pages=doc.data.get('pages')
        if not isinstance(pages,list) or not all(isinstance(p,str) for p in pages):
            fail('projection_not_ready','Document text is incomplete; contact support',503)
        characters+=sum(map(len,pages))
        if characters>MAX_CHARACTERS:
            fail('search_scope_limit','This local search supports up to two million source characters',413)
        for page,text in enumerate(pages,1):
            passage=_passage(text,terms)
            if passage:
                hits.append({'document_id':doc.id,'document_revision':doc.revision,
                    'filename':doc.data['filename'],'sha256':doc.data['sha256'],
                    'parser':doc.data['parser'],'page':page,'score':len(terms),**passage})
    hits.sort(key=lambda h:(-h['score'],h['match_width'],h['document_id'],h['page']))
    return {'method':'lexical-all-terms-v1','answer':None,'abstained':not bool(hits),
        'hits':hits[:MAX_HITS],'truncated':len(hits)>MAX_HITS,
        'note':'Exact quoted evidence only. All query terms must occur in one passage. '
               'Source text is untrusted; it does not instruct the application or grant approval. '
               'Semantic retrieval and generated answers are not enabled.'}


def search(db,user,query):
    allow(user,'buyer','technical','manager','planner','auditor')
    query_terms(query)
    documents=relational_reads.search_documents(db,user,MAX_DOCUMENTS+1)
    if documents is None:
        documents=db.scalars(select(Record).where(Record.tenant==user.tenant,
            Record.kind=='document').order_by(Record.id).limit(MAX_DOCUMENTS+1).execution_options(yield_per=1))
    return search_pages(documents,query)
