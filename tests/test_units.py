import pytest
from conftest import Clock

from chartsvc import indicators as ind
from chartsvc.breaker import CircuitBreaker, CircuitOpen
from chartsvc.cache import BytesLRU, TTLCache
from chartsvc.config import ConfigError, Settings
from chartsvc.errors import ApiError, envelope


def test_sma_and_ema():
    assert ind.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    e = ind.ema([1, 2, 3, 4, 5], 3)
    assert e[:2] == [None, None] and e[2] == 2 and e[3] == pytest.approx(3) and e[4] == pytest.approx(4)
    assert ind.ema([1], 3) == [None]
    with pytest.raises(ValueError):
        ind.sma([1], 0)


def test_rsi_bounds_and_known_values():
    up = ind.rsi(list(range(1, 30)), 14)
    assert up[13] is None and up[14] == 100.0
    flat = ind.rsi([5.0] * 20, 14)
    assert flat[-1] == 50.0
    mixed = ind.rsi([1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2], 14)
    assert 0 < mixed[-1] < 100


def test_ttl_cache_fresh_stale_and_eviction():
    clock = Clock()
    c = TTLCache(ttl=10, stale_ttl=100, max_entries=2, clock=clock)
    c.set("a", 1)
    assert c.get_fresh("a") == 1
    clock.t += 11
    assert c.get_fresh("a") is None and c.get_stale("a") == (1, 11)
    clock.t += 100
    assert c.get_stale("a") is None
    c.set("b", 2)
    c.set("c", 3)
    c.set("d", 4)
    assert len(c) == 2 and c.get_fresh("b") is None
    assert c.key_lock("x") is c.key_lock("x")


def test_bytes_lru_bounds_size_and_expires():
    clock = Clock()
    lru = BytesLRU(max_bytes=10, ttl=5, clock=clock)
    lru.set("a", b"12345")
    lru.set("b", b"12345")
    lru.set("c", b"123")
    assert lru.get("a") is None and lru.get("b") == b"12345" and lru.size_bytes == 8
    lru.set("huge", b"x" * 11)
    assert lru.get("huge") is None
    clock.t += 6
    assert lru.get("b") is None


def test_breaker_half_open_allows_one_trial():
    clock = Clock()
    b = CircuitBreaker(2, 10, clock)
    b.record_failure()
    b.record_failure()
    with pytest.raises(CircuitOpen):
        b.before_call()
    clock.t += 10
    b.before_call()
    with pytest.raises(CircuitOpen):
        b.before_call()
    b.record_failure()
    assert b.state == "open"


def test_settings_from_env():
    s = Settings.from_env({})
    assert s.api_plan == "public" and s.auth_header is None
    s = Settings.from_env({"COINGECKO_API_KEY": "k", "ALLOWED_COINS": "Bitcoin, ethereum",
                           "CACHE_TTL_SECONDS": "60", "CORS_ORIGINS": "https://a.example"})
    assert s.api_plan == "demo" and s.allowed_coins == ("bitcoin", "ethereum") and s.cache_ttl_seconds == 60
    for env in ({"COINGECKO_API_PLAN": "pro"}, {"COINGECKO_API_PLAN": "gold"}, {"CACHE_TTL_SECONDS": "x"},
                {"UPSTREAM_RETRIES": "99"}, {"LOG_LEVEL": "loud"}, {"UPSTREAM_READ_TIMEOUT": "abc"}):
        with pytest.raises(ConfigError):
            Settings.from_env(env)


def test_envelope_shape():
    assert envelope({"a": 1}) == {"success": True, "data": {"a": 1}, "error": None, "meta": {}}
    err = envelope(error=ApiError(400, "bad", "no", {"param": "x"}))
    assert err["success"] is False and err["data"] is None and err["error"]["code"] == "bad"
