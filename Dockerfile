# Single image: builds the dashboard, then serves API + dashboard + scheduler on :8000
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 COCKPIT_DB=/data/cockpit.db COCKPIT_DIST=/app/frontend/dist
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY config/ config/
COPY --from=web /web/dist frontend/dist
WORKDIR /app/backend
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
CMD ["python", "-m", "cockpit", "serve", "--port", "8000"]
