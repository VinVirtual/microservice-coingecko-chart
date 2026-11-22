import json

import pytest
import requests
from conftest import FakeResponse, candles, make_settings, volumes


def ok_ohlc(session, n=60):
    session.queue.append(FakeResponse(200, candles(n)))


def test_health_and_index(client):
    body = client.get("/health").get_json()
    assert body["success"] and body["data"]["status"] == "ok" and body["data"]["upstream_circuit"] == "closed"
    assert client.get("/").get_json()["data"]["docs"] == "/openapi.json"


def test_chart_png_defaults(client, session, renderer):
    ok_ohlc(session)
    r = client.get("/v1/chart")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data.startswith(b"\x89PNG")
    assert r.headers["X-Cache"] == "MISS" and r.headers["X-Request-ID"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    q = renderer.calls[0][0]
    assert (q.coin, q.vs, q.days, q.width, q.height, q.theme) == ("bitcoin", "usd", 30, 1200, 675, "dark")


def test_chart_is_cached_and_svg_gets_a_csp(client, session, renderer):
    ok_ohlc(session)
    url = "/v1/chart?coin=ethereum&days=7&format=svg&theme=light&indicators=sma:20,ema:50,rsi:14"
    a, b = client.get(url), client.get(url)
    assert a.mimetype == "image/svg+xml" and "default-src 'none'" in a.headers["Content-Security-Policy"]
    assert b.headers["X-Cache"] == "HIT" and len(renderer.calls) == 1 and len(session.calls) == 1
    assert renderer.calls[0][0].indicators == (("sma", 20), ("ema", 50), ("rsi", 14))


def test_volume_panel_makes_one_more_upstream_call(client, session, renderer):
    session.queue += [FakeResponse(200, candles()), FakeResponse(200, volumes())]
    assert client.get("/v1/chart?volume=true").status_code == 200
    assert session.calls[1]["url"].endswith("/market_chart") and renderer.calls[0][2] is True


@pytest.mark.parametrize("query,param", [
    ("days=max", "days"), ("days=2", "days"), ("days=abc", "days"),
    ("coin=../../etc", "coin"), ("coin=http://evil.example", "coin"), ("coin=" + "a" * 81, "coin"),
    ("vs=US-D", "vs"), ("format=gif", "format"), ("theme=neon", "theme"),
    ("width=99999", "width"), ("height=10", "height"), ("width=-5", "width"), ("scale=3", "scale"),
    ("indicators=sma:1", "indicators"), ("indicators=macd:12", "indicators"),
    ("indicators=sma:5,sma:6,sma:7,sma:8,sma:9", "indicators"), ("indicators=rsi:14,rsi:7", "indicators"),
    ("volume=maybe", "volume"), ("callback=x", "callback"), ("days=7&days=30", "days"),
])
def test_invalid_parameters_are_400_with_envelope(client, session, query, param):
    r = client.get(f"/v1/chart?{query}")
    body = r.get_json()
    assert r.status_code == 400, query
    assert body["success"] is False and body["error"]["code"] == "invalid_parameter"
    assert body["error"]["details"]["param"] == param
    assert session.calls == []  # nothing reached the upstream


def test_allowlist(app_factory, session):
    c = app_factory(make_settings(allowed_coins=("bitcoin",))).test_client()
    assert c.get("/v1/chart?coin=dogecoin").status_code == 400
    ok_ohlc(session)
    assert c.get("/v1/chart?coin=bitcoin").status_code == 200


def test_ohlc_json(client, session):
    ok_ohlc(session, 10)
    r = client.get("/v1/ohlc?coin=bitcoin&days=1")
    body = r.get_json()
    assert r.status_code == 200 and body["success"] and len(body["data"]["candles"]) == 10
    assert body["meta"]["cache"] == "MISS" and set(body["data"]["summary"]) == {
        "first_close", "last_close", "change_pct", "high", "low"}


def test_upstream_errors_map_to_envelopes(client, session):
    session.queue.append(FakeResponse(404, {}))
    r = client.get("/v1/chart?coin=nosuchcoin")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "coin_not_found"
    session.queue += [requests.ConnectionError("x")] * 3
    r = client.get("/v1/chart?coin=other")
    assert r.status_code == 503 and r.headers["Retry-After"]
    assert "ConnectionError" not in r.get_data(as_text=True) or r.get_json()["error"]["details"]["reason"]


def test_empty_upstream_data(client, session):
    session.queue.append(FakeResponse(200, []))
    r = client.get("/v1/chart?coin=newcoin")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "no_data"


def test_renderer_crash_is_a_generic_500(app_factory, session, renderer):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    renderer.render = boom
    c = app_factory().test_client()
    ok_ohlc(session)
    r = c.get("/v1/chart")
    assert r.status_code == 500 and "secret" not in r.get_data(as_text=True)
    assert r.get_json()["error"]["code"] == "internal_error"


def test_rate_limit(app_factory, session):
    c = app_factory(make_settings(rate_limit_chart="2 per minute")).test_client()
    ok_ohlc(session)
    assert [c.get("/v1/chart").status_code for _ in range(3)] == [200, 200, 429]
    r = c.get("/v1/chart")
    assert r.get_json()["error"]["code"] == "rate_limited" and "Retry-After" in r.headers
    assert c.get("/health").status_code == 200  # exempt


def test_404_405_and_legacy_routes(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    r = client.post("/v1/chart")
    assert r.status_code == 405 and "GET" in r.headers["Allow"]
    for path in ("/generate", "/tweet", "/multi", "/collage", "/individual"):
        r = client.post(path, json={"days": 1})
        assert r.status_code == 410 and r.get_json()["error"]["details"]["replacement"] == "/v1/chart"


def test_request_id_and_cors(app_factory, session):
    c = app_factory(make_settings(cors_origins=("https://ok.example",))).test_client()
    assert c.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    assert len(c.get("/health", headers={"X-Request-ID": "bad id!"}).headers["X-Request-ID"]) == 32
    assert c.get("/health", headers={"Origin": "https://ok.example"}).headers["Access-Control-Allow-Origin"]
    assert "Access-Control-Allow-Origin" not in c.get("/health", headers={"Origin": "https://evil.example"}).headers


def test_logs_are_json_with_request_id(client):
    import io
    import logging

    from chartsvc.logs import JsonFormatter
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logging.getLogger("chartsvc").addHandler(handler)
    try:
        client.get("/health", headers={"X-Request-ID": "log-test"})
    finally:
        logging.getLogger("chartsvc").removeHandler(handler)
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    req = [entry for entry in lines if entry["msg"] == "request"][-1]
    assert req["request_id"] == "log-test" and req["status"] == 200 and req["path"] == "/health"


def test_openapi_matches_routes(app_factory):
    app = app_factory()
    spec = app.test_client().get("/openapi.json").get_json()
    routes = {r.rule for r in app.url_map.iter_rules()} - {"/static/<path:filename>", "/"}
    routes -= {"/generate", "/tweet", "/multi", "/collage", "/individual"}
    assert set(spec["paths"]) == routes
    documented = {p["name"] for p in spec["paths"]["/v1/chart"]["get"]["parameters"]}
    assert documented == {"coin", "vs", "days", "format", "theme", "width", "height", "scale",
                          "indicators", "volume"}
