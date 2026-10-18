# Futran Audit Platform: one container serving the API and the web app.
# Stage 1 builds the React app; stage 2 is the Python service with the built files.

FROM node:20-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN mkdir -p ../backend/app/static && npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8000 \
    DATABASE_URL=sqlite:///./data/app.db FILE_STORE=local:./data/files TRUST_PROXY_HEADERS=true
WORKDIR /app/backend
COPY backend/ ./
COPY --from=web /src/backend/app/static ./app/static
RUN pip install -e . \
 && chmod -R a+rX /app/backend \
 && useradd --create-home --uid 10001 futran \
 && mkdir -p data \
 && chown -R futran:futran /app/backend/data
USER futran
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health', timeout=4)"
# Migrate, load reference data (only what is missing), then serve. Render and Azure set PORT.
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli seed-reference && exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
