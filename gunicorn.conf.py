"""Gunicorn settings. Every value can be overridden with an environment variable."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Rendering is CPU-bound (Kaleido runs a headless Chromium per worker), so keep
# workers close to the CPU count and use a few threads for upstream I/O waits.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "45"))
graceful_timeout = 20
keepalive = 5
# Recycle workers now and then to bound memory growth of the Chromium helper.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "500"))
max_requests_jitter = 50
limit_request_line = 2048
limit_request_fields = 50
accesslog = None          # the app writes one JSON log line per request
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
