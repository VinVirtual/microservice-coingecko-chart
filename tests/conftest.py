"""Fixtures. Tests never touch the network: sockets are blocked and the
CoinGecko session is a fake that replays queued responses."""

from __future__ import annotations

import io
import json
import math
import random
import socket
from typing import Any, Dict, List, Optional

import pytest
import requests

from chartsvc.app import create_app
from chartsvc.coingecko import CoinGeckoClient
from chartsvc.config import Settings

T0 = 1_772_582_400_000  # 2026-03-04T00:00:00Z


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_connect = socket.socket.connect

    def guarded(self, address):
        if self.family == getattr(socket, "AF_UNIX", None):
            return real_connect(self, address)
        raise RuntimeError(f"network access attempted in a test: {address!r}")
    monkeypatch.setattr(socket.socket, "connect", guarded)


def candles(n: int = 60, start: float = 100.0, step_ms: int = 4 * 3_600_000, seed: int = 1) -> List[list]:
    rng = random.Random(seed)
    out, price = [], start
    for i in range(n):
        o = price
        c = max(0.01, o * (1 + rng.gauss(0, 0.012) + 0.002 * math.sin(i / 6)))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        out.append([T0 + i * step_ms, round(o, 6), round(h, 6), round(lo, 6), round(c, 6)])
        price = c
    return out


def volumes(n: int = 60) -> Dict[str, Any]:
    return {"prices": [], "market_caps": [],
            "total_volumes": [[T0 + i * 3_600_000, 1e9 + i * 1e7] for i in range(n)]}


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None, headers: Optional[dict] = None,
                 raw_bytes: Optional[bytes] = None):
        self.status_code = status
        self.headers = headers or {}
        data = raw_bytes if raw_bytes is not None else json.dumps(body).encode()
        self.raw = _Raw(data)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Raw:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, n: int, decode_content: bool = True) -> bytes:
        return self._buf.read(n)


class FakeSession(requests.Session):
    """Queue responses (or exceptions); records every call."""

    def __init__(self, responses: Optional[list] = None):
        super().__init__()
        self.queue = list(responses or [])
        self.calls: List[dict] = []

    def get(self, url, **kwargs):  # type: ignore[override]
        self.calls.append({"url": url, **kwargs})
        if not self.queue:
            raise AssertionError(f"unexpected upstream call: {url}")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeRenderer:
    def __init__(self):
        self.calls = []

    def render(self, q, candles, volumes=None, source_label="Data: CoinGecko"):
        self.calls.append((q, len(candles), volumes is not None))
        return b"\x89PNG\r\n\x1a\nfake" if q.fmt == "png" else b"<svg xmlns='http://www.w3.org/2000/svg'/>"


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_settings(**overrides) -> Settings:
    base = dict(retries=2, breaker_failures=3, breaker_reset_seconds=30, cache_ttl_seconds=300,
                stale_ttl_seconds=3600, rate_limit_chart="1000 per minute", rate_limit_data="1000 per minute")
    base.update(overrides)
    return Settings(**base)


def make_client(session: FakeSession, clock: Optional[Clock] = None, **overrides) -> CoinGeckoClient:
    return CoinGeckoClient(make_settings(**overrides), session, clock=clock or Clock(), sleep=lambda s: None)


@pytest.fixture()
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture()
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture()
def app_factory(session, renderer):
    def build(settings: Optional[Settings] = None, client: Optional[CoinGeckoClient] = None):
        settings = settings or make_settings()
        client = client or CoinGeckoClient(settings, session, clock=Clock(), sleep=lambda s: None)
        app = create_app(settings, client=client, renderer=renderer)
        app.testing = True
        return app
    return build


@pytest.fixture()
def client(app_factory):
    return app_factory().test_client()
