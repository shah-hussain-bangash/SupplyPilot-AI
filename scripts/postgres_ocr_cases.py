"""Projection/API contract checks; actual OCR engines are tested separately."""
from pathlib import Path
from unittest.mock import patch


def ocr_workflow(client,check,tokens):
    from supplypilot import config
    from supplypilot.document_ocr import OCRUnavailable
    raw=(Path(__file__).resolve().parents[1]/'backend/tests/fixtures/ocr/clean-scan.pdf').read_bytes()
    text='SKU: PIPE-DN50\nQuantity: 30\nGrade: ASTM A106 Grade B\n'
    metadata={'engine':'tesseract','language':'eng','pages':[1],'human_review_required':True}
    before={k:client.get('/api/v1/records/'+k,headers=tokens['buyer']).json()
            for k in ('offer','plan','order','exception')}
    with patch.object(config,'LOCAL_OCR_ENABLED',True), \
         patch('supplypilot.main.extract_scanned_pages',return_value=([text],metadata)):
        response=client.post('/api/v1/documents',headers=tokens['supplier-gulf'],
            files={'file':('synthetic-ocr.pdf',raw,'application/pdf')})
    check(response.status_code==201,'Synthetic OCR contract upload succeeds against PostgreSQL')
    doc=response.json();identity=doc['id']
    detail=client.get('/api/v1/record/'+identity,headers=tokens['supplier-gulf'])
    check(detail.status_code==200 and detail.json()==doc and doc['data']['ocr']==metadata,
          'Relational document metadata retains OCR provenance and supplier ownership')
    evidence=client.get('/api/v1/documents/'+identity+'/evidence',headers=tokens['supplier-gulf'])
    check(evidence.status_code==200 and evidence.json()['pages']==[text] and
          evidence.json()['parser']=='pypdf/tesseract-v1','Relational evidence retains OCR text and parser provenance')
    jobs=client.get('/api/v1/records/job',headers=tokens['buyer']).json()
    job=next(x for x in jobs['items'] if x['data']['document_id']==identity)
    check(job['data']['result']['ocr']==metadata and len(job['data']['result']['candidates'])==3,
          'Relational job result preserves OCR metadata and three candidates')
    check(all(not c['reviewed'] and text[c['start']:c['end']]==c['raw'] for c in job['data']['result']['candidates']),
          'OCR contract keeps unreviewed candidates and exact text-offset anchors')
    for role in ('supplier-desert','other-buyer'):
        response=client.get('/api/v1/documents/'+identity+'/evidence',headers=tokens[role])
        check(response.status_code==404,role+' cannot read OCR source evidence')
    response=client.get('/api/v1/record/'+job['id'],headers=tokens['supplier-gulf'])
    check(response.status_code==404,'Supplier cannot inspect internal OCR processing jobs')
    check(all(client.get('/api/v1/records/'+k,headers=tokens['buyer']).json()==v for k,v in before.items()),
          'OCR contract creates no approval, offer edit, order or exception resolution')
    with patch.object(config,'LOCAL_OCR_ENABLED',True), \
         patch('supplypilot.main.extract_scanned_pages',side_effect=OCRUnavailable('synthetic timeout')):
        failed=client.post('/api/v1/documents',headers=tokens['buyer'],
            files={'file':('timeout-ocr.pdf',raw,'application/pdf')})
    check(failed.status_code==201 and failed.json()['data']['status']=='quarantined',
          'OCR timeout contract remains representable in document projections')
    check(client.get('/api/v1/records/job',headers=tokens['buyer']).json()['total']==jobs['total'],
          'OCR failure creates no fabricated completed processing result')
