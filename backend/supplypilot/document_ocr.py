"""Optional local English OCR for image-only PDF pages; no external service."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

MAX_OCR_PAGES = 5
MAX_PAGE_TEXT = 20000
MAX_RASTER_BYTES = 20 * 1024 * 1024
DOCUMENT_TIMEOUT = 30


class OCRUnavailable(ValueError):
    pass


def extract_scanned_pages(raw, pages):
    """Return a new page list and provenance, or fail the complete OCR attempt.

    Only empty text layers are eligible. This deliberately does not infer that
    a short/nonempty text layer is complete or that extracted facts are correct.
    Paths and arguments are operator/code controlled, never document content.
    """
    missing=[i for i,text in enumerate(pages) if not text.strip()]
    if not missing:return list(pages),None
    if len(missing)>MAX_OCR_PAGES:raise OCRUnavailable('OCR page limit exceeded')
    renderer=shutil.which('pdftoppm')
    engine=shutil.which('tesseract')
    if not renderer or not engine:raise OCRUnavailable('Local OCR tools unavailable')
    deadline=time.monotonic()+DOCUMENT_TIMEOUT
    def run(command):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise OCRUnavailable('OCR time limit exceeded')
        try:
            subprocess.run(command,check=True,timeout=remaining,stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,shell=False)
        except (OSError,subprocess.SubprocessError) as exc:
            raise OCRUnavailable('Local OCR failed or exceeded its time limit') from exc
    result=list(pages)
    with tempfile.TemporaryDirectory(prefix='supplypilot-ocr-') as folder:
        folder=Path(folder);source=folder/'source.pdf';source.write_bytes(raw)
        for index in missing:
            image=folder/('page-'+str(index+1))
            run([renderer,'-f',str(index+1),'-l',str(index+1),'-singlefile',
                 '-scale-to','2400','-gray','-png',str(source),str(image)])
            raster=image.with_suffix('.png')
            if not raster.is_file() or raster.stat().st_size>MAX_RASTER_BYTES:
                raise OCRUnavailable('OCR raster missing or too large')
            output=folder/('text-'+str(index+1))
            run([engine,str(raster),str(output),'-l','eng','--psm','3'])
            text_file=output.with_suffix('.txt')
            if not text_file.is_file() or text_file.stat().st_size>MAX_PAGE_TEXT*4:
                raise OCRUnavailable('OCR text missing or too large')
            text=text_file.read_text(encoding='utf-8')
            if not text.strip() or len(text)>MAX_PAGE_TEXT:
                raise OCRUnavailable('OCR page unreadable or too large')
            result[index]=text
    return result,{'engine':'tesseract','language':'eng','pages':[i+1 for i in missing],
                   'raster_max_edge':2400,'human_review_required':True,
                   'scope':'Empty PDF text layers only; no layout, table or handwriting accuracy claim'}
