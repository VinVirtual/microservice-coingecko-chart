import pytest
import requests
from conftest import Clock, FakeResponse, FakeSession, candles, make_client, volumes

from chartsvc.coingecko import MAX_BODY_BYTES, parse_ohlc, parse_volumes
from chartsvc.config import PRO_BASE, PUBLIC_BASE
from chartsvc.errors import ApiError


def test_parse_ohlc_sorts_dedupes_and_validates():
    rows = candles(5)
    parsed = parse_ohlc(list(reversed(rows)) + [rows[0]])
    assert [c.ts_ms for c in parsed] == [r[0] for r in rows]
    for bad in ([[1, 2, 3]], [[1, 2, 1, 3, 2]], [[1, "2", 3, 1, 2]], [[1, float("nan"), 3, 1, 2]],
                {"x": 1}, [[1, -1, 3, -2, 2]], [[True, 1, 1, 1, 1]]):
        with pytest.raises(ValueError):
            parse_ohlc(bad)


def test_parse_volumes():
    assert parse_volumes(volumes(3))[0][1] == 1e9
    with pytest.raises(ValueError):
        parse_volumes({"total_volumes": [[1]]})


def test_success_is_cached_then_served_from_cache():
    s = FakeSession([FakeResponse(200, candles())])
    c = make_client(s)
    first = c.ohlc("bitcoin", "usd", 30)
    second = c.ohlc("bitcoin", "usd", 30)
    assert first.cache == "MISS" and second.cache == "HIT" and len(s.calls) == 1
    call = s.calls[0]
    assert call["url"] == PUBLIC_BASE + "/coins/bitcoin/ohlc"
    assert call["params"] == {"vs_currency": "usd", "days": "30"}
    assert call["timeout"] == (3.05, 10.0) and call["allow_redirects"] is False


def test_api_key_header_by_plan():
    demo = make_client(FakeSession(), api_key="k", api_plan="demo")
    assert demo.session.headers["x-cg-demo-api-key"] == "k"
    pro = make_client(FakeSession(), api_key="k", api_plan="pro")
    assert pro.session.headers["x-cg-pro-api-key"] == "k" and pro.settings.base_url == PRO_BASE
    assert "x-cg-demo-api-key" not in make_client(FakeSession()).session.headers


def test_retries_transient_errors_then_succeeds():
    s = FakeSession([requests.ConnectTimeout("t"), FakeResponse(502), FakeResponse(200, candles())])
    assert make_client(s).ohlc("bitcoin", "usd", 1).cache == "MISS"
    assert len(s.calls) == 3


def test_429_honours_retry_after():
    sleeps = []
    s = FakeSession([FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, candles())])
    c = make_client(s)
    c._sleep = sleeps.append
    c.ohlc("bitcoin", "usd", 1)
    assert sleeps == [3.0]


def test_404_and_400_are_not_retried_and_do_not_trip_breaker():
    s = FakeSession([FakeResponse(404, {"error": "coin not found"}), FakeResponse(400, {})])
    c = make_client(s)
    with pytest.raises(ApiError) as e:
        c.ohlc("nope", "usd", 1)
    assert e.value.status == 404 and e.value.code == "coin_not_found"
    with pytest.raises(ApiError) as e:
        c.ohlc("bitcoin", "xyz", 1)
    assert e.value.status == 400 and len(s.calls) == 2 and c.breaker.state == "closed"


def test_bad_credentials_are_a_502():
    with pytest.raises(ApiError) as e:
        make_client(FakeSession([FakeResponse(401)])).ohlc("bitcoin", "usd", 1)
    assert e.value.status == 502 and e.value.code == "upstream_auth"


def test_outage_without_cache_is_503_with_retry_after():
    s = FakeSession([requests.ConnectionError("down")] * 3)
    with pytest.raises(ApiError) as e:
        make_client(s).ohlc("bitcoin", "usd", 1)
    assert e.value.status == 503 and e.value.headers["Retry-After"]


def test_stale_cache_is_served_during_outage():
    clock = Clock()
    s = FakeSession([FakeResponse(200, candles())] + [FakeResponse(503)] * 3)
    c = make_client(s, clock)
    c.ohlc("bitcoin", "usd", 1)
    clock.t += 301  # past the fresh TTL, inside the stale window
    stale = c.ohlc("bitcoin", "usd", 1)
    assert stale.cache == "STALE" and stale.age_seconds == pytest.approx(301)
    clock.t += 3600
    s.queue = [FakeResponse(503)] * 3
    with pytest.raises(ApiError):
        c.ohlc("bitcoin", "usd", 1)


def test_circuit_breaker_opens_and_recovers():
    clock = Clock()
    s = FakeSession([FakeResponse(500)] * 9)
    c = make_client(s, clock, retries=0, breaker_failures=3)
    for _ in range(3):
        with pytest.raises(ApiError):
            c.ohlc("bitcoin", "usd", 1)
    assert c.breaker.state == "open"
    calls = len(s.calls)
    with pytest.raises(ApiError) as e:
        c.ohlc("bitcoin", "usd", 1)
    assert len(s.calls) == calls and e.value.details["reason"] == "circuit_open"
    clock.t += 31
    assert c.breaker.state == "half-open"
    s.queue = [FakeResponse(200, candles())]
    assert c.ohlc("bitcoin", "usd", 1).cache == "MISS" and c.breaker.state == "closed"


def test_oversized_or_malformed_payloads_count_as_failures():
    big = FakeResponse(200, raw_bytes=b"[" + b" " * MAX_BODY_BYTES + b"]")
    bad = FakeResponse(200, raw_bytes=b"<html>")
    c = make_client(FakeSession([big, bad]), retries=0, breaker_failures=5)
    for _ in range(2):
        with pytest.raises(ApiError) as e:
            c.ohlc("bitcoin", "usd", 1)
        assert e.value.details["reason"] == "bad_payload"


def test_volumes_endpoint():
    s = FakeSession([FakeResponse(200, volumes())])
    v = make_client(s).volumes("bitcoin", "usd", 7)
    assert s.calls[0]["url"].endswith("/coins/bitcoin/market_chart") and len(v.value) == 60
