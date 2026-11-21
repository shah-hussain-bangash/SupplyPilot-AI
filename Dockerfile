FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data PYTHONPATH=/app/backend
WORKDIR /app/backend
COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --uid 10001 --create-home appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "supplypilot.main:app", "--host", "0.0.0.0", "--port", "8000"]
