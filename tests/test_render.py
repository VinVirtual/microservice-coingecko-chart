"""Real rendering through Plotly + Kaleido (no network)."""

import struct

import pytest
from conftest import candles, volumes

from chartsvc.coingecko import parse_ohlc, parse_volumes
from chartsvc.render import Renderer, build_figure, summary
from chartsvc.validation import ChartQuery

CANDLES = parse_ohlc(candles(80))


def png_size(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_figure_layers():
    q = ChartQuery("bitcoin", "usd", 30, indicators=(("sma", 20), ("ema", 9), ("rsi", 14)), volume=True)
    fig = build_figure(q, CANDLES, parse_volumes(volumes()))
    names = [t.name for t in fig.data]
    assert names == ["price", "SMA 20", "EMA 9", "24h volume", "RSI 14"]
    assert "BITCOIN" in fig.layout.title.text and "30D" in fig.layout.title.text
    assert any("CoinGecko" in (a.text or "") for a in fig.layout.annotations)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_png_has_requested_pixel_size(theme):
    q = ChartQuery("bitcoin", "usd", 30, width=640, height=360, scale=2, theme=theme)
    assert png_size(Renderer().render(q, CANDLES)) == (1280, 720)


def test_svg_output_has_no_scripts():
    q = ChartQuery("bitcoin", "usd", 30, fmt="svg", width=500, height=300, indicators=(("sma", 5),))
    svg = Renderer().render(q, CANDLES).decode()
    assert svg.startswith("<svg") and "<script" not in svg.lower()


def test_summary():
    s = summary(CANDLES)
    assert s["low"] <= s["first_close"] <= s["high"] and s["low"] <= s["last_close"] <= s["high"]


def test_indicator_without_enough_candles_says_so():
    q = ChartQuery("bitcoin", "usd", 1, indicators=(("ema", 200),))
    fig = build_figure(q, CANDLES)
    assert fig.data[1].name == "EMA 200 (needs 200 candles)"
