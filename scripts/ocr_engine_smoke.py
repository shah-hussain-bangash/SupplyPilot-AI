"""Real engine smoke test using only public synthetic fixtures, never a database."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
from pypdf import PdfReader

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('document_ocr',root/'backend/supplypilot/document_ocr.py')
ocr=importlib.util.module_from_spec(spec);spec.loader.exec_module(ocr)
fixtures=root/'backend/tests/fixtures/ocr'
labels=json.loads((fixtures/'labels.json').read_text())
results=[]
for case in labels['cases']:
    raw=(fixtures/case['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==case['sha256']
    pages=[p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages]
    assert all(not page.strip() for page in pages),'Fixture must have no embedded text'
    pages,metadata=ocr.extract_scanned_pages(raw,pages)
    extracted={m[1].lower():m[2].strip() for text in pages for m in re.finditer(
        r'(?i)\b(quantity|qty|grade|standard|sku)\s*[:=]\s*([^\n;]{1,100})',text)}
    assert extracted==case['fields'],(case['file'],extracted)
    assert metadata['pages']==[1] and metadata['human_review_required'] is True
    results.append({'fixture':case['file'],'fields_exact':len(extracted),'expected_fields':len(case['fields'])})
try:ocr.extract_scanned_pages((fixtures/'blank-scan.pdf').read_bytes(),[''])
except ocr.OCRUnavailable:pass
else:raise AssertionError('Blank scan must fail closed')
version=subprocess.run(['tesseract','--version'],check=True,capture_output=True,text=True).stdout.splitlines()[0]
print(json.dumps({'result':'passed','engine':version,'cases':results,'blank_scan':'rejected',
                  'scope':labels['scope'],'network':'run this smoke container with --network none'},indent=2))
