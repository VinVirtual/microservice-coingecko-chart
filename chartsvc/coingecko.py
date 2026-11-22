"""CoinGecko client: timeouts, retries with backoff, circuit breaker, caching.

Only two endpoints are used, both on a fixed base URL; the caller can only
choose already-validated path and query values, so user input never decides
which host is contacted.

* ``/coins/{id}/ohlc``         candles (timestamp = candle close, ms)
* ``/coins/{id}/market_chart`` ``total_volumes`` = rolling 24h volume
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, Tuple, TypeVar

import requests

from .breaker import CircuitBreaker, CircuitOpen
from .cache import TTLCache
from .config import Settings
from .errors import ApiError

log = logging.getLogger("chartsvc.upstream")
T = TypeVar("T")

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_POINTS = 5000
BACKOFF_CAP_SECONDS = 5.0
USER_AGENT = "coingecko-chart-service/2 (+https://github.com/VinVirtual/microservice-coingecko-chart)"


@dataclass(frozen=True)
class Candle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Fetched(Generic[T]):
    value: T
    cache: str          # HIT | MISS | STALE
    age_seconds: float = 0.0


class UpstreamUnavailable(Exception):
    def __init__(self, reason: str, retry_after: Optional[float] = None):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def _finite(x: Any) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"not a finite number: {x!r}")
    return float(x)


def parse_ohlc(raw: Any) -> Tuple[Candle, ...]:
    """Validate ``[[ts, o, h, l, c], ...]`` and return sorted, de-duplicated candles."""
    if not isinstance(raw, list):
        raise ValueError("expected a list")
    if len(raw) > MAX_POINTS:
        raise ValueError(f"too many points ({len(raw)})")
    by_ts = {}
    for row in raw:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError("expected [timestamp, open, high, low, close]")
        ts, o, h, lo, c = (_finite(v) for v in row)
        if min(o, h, lo, c) < 0 or h < max(o, c, lo) or lo > min(o, c):
            raise ValueError("inconsistent candle")
        by_ts[int(ts)] = Candle(int(ts), o, h, lo, c)
    return tuple(by_ts[k] for k in sorted(by_ts))


def parse_volumes(raw: Any) -> Tuple[Tuple[int, float], ...]:
    if not isinstance(raw, dict) or not isinstance(raw.get("total_volumes"), list):
        raise ValueError("expected an object with total_volumes")
    rows = raw["total_volumes"]
    if len(rows) > 10 * MAX_POINTS:
        raise ValueError("too many points")
    out = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("expected [timestamp, volume]")
        ts, v = _finite(row[0]), _finite(row[1])
        out[int(ts)] = max(0.0, v)
    return tuple(sorted(out.items()))


class CoinGeckoClient:
    def __init__(
        self,
        settings: Settings,
        session: Optional[requests.Session] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
        if settings.auth_header:
            self.session.headers[settings.auth_header[0]] = settings.auth_header[1]
        self._sleep = sleep
        self.breaker = CircuitBreaker(settings.breaker_failures, settings.breaker_reset_seconds, clock)
        self.cache: TTLCache[Any] = TTLCache(settings.cache_ttl_seconds, settings.stale_ttl_seconds,
                                             settings.cache_max_entries, clock)

    # ----- public -----

    def ohlc(self, coin: str, vs: str, days: int) -> Fetched[Tuple[Candle, ...]]:
        return self._cached(("ohlc", coin, vs, days), f"/coins/{coin}/ohlc",
                            {"vs_currency": vs, "days": str(days)}, parse_ohlc)

    def volumes(self, coin: str, vs: str, days: int) -> Fetched[Tuple[Tuple[int, float], ...]]:
        return self._cached(("volume", coin, vs, days), f"/coins/{coin}/market_chart",
                            {"vs_currency": vs, "days": str(days)}, parse_volumes)

    # ----- internals -----

    def _cached(self, key, path: str, params: dict, parser: Callable[[Any], T]) -> Fetched[T]:
        hit = self.cache.get_fresh(key)
        if hit is not None:
            return Fetched(hit, "HIT")
        with self.cache.key_lock(key):
            hit = self.cache.get_fresh(key)  # another thread may have filled it
            if hit is not None:
                return Fetched(hit, "HIT")
            try:
                value = self._request(path, params, parser)
            except UpstreamUnavailable as exc:
                stale = self.cache.get_stale(key)
                if stale is not None:
                    log.warning("serving stale data", extra={"reason": exc.reason, "path": path})
                    return Fetched(stale[0], "STALE", stale[1])
                headers = {"Retry-After": str(max(1, int(exc.retry_after or 30)))}
                raise ApiError(503, "upstream_unavailable",
                               "Market data is temporarily unavailable. Try again shortly.",
                               {"reason": exc.reason}, headers) from exc
            self.cache.set(key, value)
            return Fetched(value, "MISS")

    def _backoff(self, attempt: int, retry_after: Optional[float]) -> None:
        delay = retry_after if retry_after is not None else 0.5 * (2 ** attempt) + random.uniform(0, 0.25)  # noqa: S311
        self._sleep(min(BACKOFF_CAP_SECONDS, max(0.0, delay)))

    def _request(self, path: str, params: dict, parser: Callable[[Any], T]) -> T:
        try:
            self.breaker.before_call()
        except CircuitOpen as exc:
            raise UpstreamUnavailable("circuit_open", exc.retry_after) from exc
        url = self.settings.base_url + path
        last = "unknown"
        retry_after: Optional[float] = None
        for attempt in range(self.settings.retries + 1):
            if attempt:
                self._backoff(attempt - 1, retry_after)
            retry_after = None
            started = time.perf_counter()
            try:
                resp = self.session.get(url, params=params, stream=True, allow_redirects=False,
                                        timeout=(self.settings.connect_timeout, self.settings.read_timeout))
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = type(exc).__name__
                log.warning("upstream request failed", extra={"path": path, "error": last, "attempt": attempt})
                continue
            status = resp.status_code
            log.info("upstream", extra={"path": path, "status": status, "attempt": attempt,
                                        "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
            if status == 200:
                return self._decode(resp, parser)
            resp.close()
            if status == 404:
                self.breaker.record_success()
                raise ApiError(404, "coin_not_found", "CoinGecko does not know that coin id.")
            if status in (400, 422):
                self.breaker.record_success()
                raise ApiError(400, "invalid_parameter",
                               "CoinGecko rejected the request; check coin and vs_currency.")
            if status in (401, 403):
                self.breaker.record_failure()
                log.error("upstream rejected credentials", extra={"status": status})
                raise ApiError(502, "upstream_auth", "The service's CoinGecko credentials were rejected.")
            if status == 429:
                last = "rate_limited"
                ra = resp.headers.get("Retry-After", "")
                retry_after = float(ra) if ra.isdigit() else None
                continue
            last = f"http_{status}"
        self.breaker.record_failure()
        raise UpstreamUnavailable(last, retry_after)

    def _decode(self, resp: requests.Response, parser: Callable[[Any], T]) -> T:
        try:
            body = resp.raw.read(MAX_BODY_BYTES + 1, decode_content=True)
        finally:
            resp.close()
        try:
            if len(body) > MAX_BODY_BYTES:
                raise ValueError("response too large")
            value = parser(json.loads(body))
        except ValueError as exc:
            self.breaker.record_failure()
            log.error("bad upstream payload", extra={"error": str(exc)})
            raise UpstreamUnavailable("bad_payload") from exc
        self.breaker.record_success()
        return value
