# syntax=docker/dockerfile:1

# ---- 1. build the React + Tailwind front end --------------------------------
FROM node:22-slim AS web
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY tailwind.config.cjs ./
COPY web ./web
COPY static/index.html ./static/index.html
RUN npm run build

# ---- 2. the app: FastAPI serves the API and the built UI from one process ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DB_PATH=/data/workpaper.db PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --system --uid 10001 --no-create-home app \
 && mkdir -p /data && chown app /data
COPY app ./app
COPY data ./data
COPY static ./static
COPY --from=web /src/static/app ./static/app
COPY scripts/docker-entrypoint.sh /usr/local/bin/entrypoint
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
# The entrypoint fixes ownership of a mounted volume, then drops to the unprivileged user.
ENTRYPOINT ["/usr/local/bin/entrypoint"]
# One worker on purpose: the event log is a single SQLite file and live updates fan out in-process.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
