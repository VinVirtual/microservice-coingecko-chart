# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim
# Fonts for chart text; nothing else is needed (Kaleido 0.2.1 bundles Chromium).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOME=/tmp
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root gunicorn.conf.py ./
COPY --chown=root:root chartsvc ./chartsvc
USER app:app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=2)"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "chartsvc.wsgi:app"]
