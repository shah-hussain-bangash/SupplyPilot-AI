FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pypdf==6.21.3
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "scripts/ocr_engine_smoke.py"]
