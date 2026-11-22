"""Flask application factory and routes."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Optional

from flask import Flask, Response, g, jsonify, request
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import __version__, logs
from .cache import BytesLRU
from .coingecko import CoinGeckoClient
from .config import Settings
from .errors import ApiError, envelope
from .openapi import spec
from .render import Renderer, summary
from .validation import parse_chart_query, parse_data_query

log = logging.getLogger("chartsvc.http")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LEGACY_ROUTES = ("/generate", "/tweet", "/multi", "/collage", "/individual")
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def _error_response(err: ApiError) -> Response:
    resp = jsonify(envelope(error=err, meta={"request_id": getattr(g, "request_id", None)}))
    resp.status_code = err.status
    resp.headers.update(err.headers)
    return resp


def create_app(settings: Optional[Settings] = None, *, client: Optional[CoinGeckoClient] = None,
               renderer: Optional[Renderer] = None) -> Flask:
    settings = settings or Settings.from_env()
    logs.configure(settings.log_level)
    app = Flask(__name__)
    app.json.sort_keys = False
    if settings.trusted_proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxies, x_proto=settings.trusted_proxies)
    client = client or CoinGeckoClient(settings)
    renderer = renderer or Renderer()
    images = BytesLRU(settings.image_cache_max_bytes, settings.cache_ttl_seconds)
    limiter = Limiter(get_remote_address, app=app, storage_uri=settings.rate_limit_storage_uri,
                      headers_enabled=True, strategy="moving-window")
    app.extensions["chartsvc"] = {"settings": settings, "client": client, "images": images}

    @app.before_request
    def _start() -> None:
        rid = request.headers.get("X-Request-ID", "")
        g.request_id = rid if _REQUEST_ID_RE.match(rid) else uuid.uuid4().hex
        g.started = time.perf_counter()

    @app.after_request
    def _finish(resp: Response) -> Response:
        resp.headers["X-Request-ID"] = g.get("request_id", "")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Cache-Control", "no-store")
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        log.info("request", extra={
            "method": request.method, "path": request.path, "status": resp.status_code,
            "duration_ms": round((time.perf_counter() - g.get("started", time.perf_counter())) * 1000, 1),
            "cache": resp.headers.get("X-Cache"), "remote": get_remote_address(),
        })
        return resp

    @app.errorhandler(ApiError)
    def _api_error(err: ApiError) -> Response:
        return _error_response(err)

    @app.errorhandler(RateLimitExceeded)
    def _rate_limited(err: RateLimitExceeded) -> Response:
        return _error_response(ApiError(429, "rate_limited", "Too many requests. Slow down and retry.",
                                        {"limit": str(err.description)}))

    @app.errorhandler(HTTPException)
    def _http_error(err: HTTPException) -> Response:
        code = {404: "not_found", 405: "method_not_allowed"}.get(err.code or 500, "http_error")
        resp = _error_response(ApiError(err.code or 500, code, err.description or err.name))
        if err.code == 405 and hasattr(err, "valid_methods") and err.valid_methods:
            resp.headers["Allow"] = ", ".join(err.valid_methods)
        return resp

    @app.errorhandler(Exception)
    def _unexpected(err: Exception) -> Response:
        log.exception("unhandled error")
        return _error_response(ApiError(500, "internal_error", "Something went wrong on our side."))

    @app.get("/")
    @limiter.exempt
    def index() -> Response:
        return jsonify(envelope({"service": "coingecko-chart", "version": __version__,
                                 "docs": "/openapi.json", "chart": "/v1/chart?coin=bitcoin&days=30"}))

    @app.get("/health")
    @limiter.exempt
    def health() -> Response:
        return jsonify(envelope({"status": "ok", "version": __version__,
                                 "upstream_circuit": client.breaker.state,
                                 "cache": {"entries": len(client.cache), "hits": client.cache.hits,
                                           "misses": client.cache.misses, "image_bytes": images.size_bytes}}))

    @app.get("/openapi.json")
    @limiter.exempt
    def openapi() -> Response:
        resp = jsonify(spec())
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @app.get("/v1/ohlc")
    @limiter.limit(settings.rate_limit_data)
    def ohlc() -> Response:
        q = parse_data_query(request.args, settings)
        fetched = client.ohlc(q.coin, q.vs, q.days)
        if not fetched.value:
            raise ApiError(404, "no_data", "CoinGecko returned no candles for this range.")
        resp = jsonify(envelope(
            {"coin": q.coin, "vs": q.vs, "days": q.days, "summary": summary(fetched.value),
             "candles": [[c.ts_ms, c.open, c.high, c.low, c.close] for c in fetched.value]},
            meta={"request_id": g.request_id, "cache": fetched.cache, "source": "CoinGecko",
                  "candle_timestamp": "close time, epoch ms"}))
        resp.headers["X-Cache"] = fetched.cache
        resp.headers["Cache-Control"] = f"public, max-age={min(60, settings.cache_ttl_seconds)}"
        return resp

    @app.get("/v1/chart")
    @limiter.limit(settings.rate_limit_chart)
    def chart() -> Response:
        q = parse_chart_query(request.args, settings)
        fetched = client.ohlc(q.coin, q.vs, q.days)
        if len(fetched.value) < 2:
            raise ApiError(404, "no_data", "Not enough candles to draw a chart for this range.")
        cache_state = fetched.cache
        body = images.get(q.cache_key) if cache_state == "HIT" else None
        if body is None:
            volumes = None
            if q.volume:
                vol = client.volumes(q.coin, q.vs, q.days)
                volumes = vol.value
                if vol.cache == "STALE":
                    cache_state = "STALE"
            body = renderer.render(q, fetched.value, volumes)
            if cache_state != "STALE":
                images.set(q.cache_key, body)
        mime = "image/svg+xml" if q.fmt == "svg" else "image/png"
        resp = Response(body, mimetype=mime)
        resp.headers["X-Cache"] = cache_state
        resp.headers["Cache-Control"] = f"public, max-age={min(60, settings.cache_ttl_seconds)}"
        if q.fmt == "svg":
            resp.headers["Content-Security-Policy"] = SVG_CSP
        return resp

    def _gone() -> Response:
        return _error_response(ApiError(
            410, "endpoint_removed",
            "This v1 endpoint was removed in 2.0. Request an image from /v1/chart instead.",
            {"replacement": "/v1/chart", "docs": "/openapi.json"}))

    for path in LEGACY_ROUTES:
        app.add_url_rule(path, f"gone_{path.strip('/')}", limiter.exempt(_gone), methods=["GET", "POST"])

    return app
