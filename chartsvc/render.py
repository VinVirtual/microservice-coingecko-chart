"""Plotly figure building and image export (PNG / SVG via Kaleido)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, List, Optional, Sequence, Tuple

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import indicators as ind
from .coingecko import Candle
from .validation import ChartQuery


@dataclass(frozen=True)
class Theme:
    paper: str
    plot: str
    grid: str
    text: str
    muted: str
    up: str
    down: str
    lines: Tuple[str, ...]
    volume: str
    rsi: str


THEMES: Dict[str, Theme] = {
    "dark": Theme(paper="#0f0f17", plot="#0f0f17", grid="#24243a", text="#e8e8f0", muted="#8b8ba3",
                  up="#22c39a", down="#f0616d", lines=("#f5b14c", "#7aa2ff", "#d58cff", "#5fd4e8"),
                  volume="#5b6b8c", rsi="#d58cff"),
    "light": Theme(paper="#ffffff", plot="#ffffff", grid="#e6e8ee", text="#16181d", muted="#5d6472",
                   up="#0f9d74", down="#d63b4a", lines=("#c77700", "#2457d6", "#8a3fd1", "#0e8aa0"),
                   volume="#9aa5b8", rsi="#8a3fd1"),
}
FONT = "Inter, 'DejaVu Sans', Arial, sans-serif"


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}"
    return f"{p:.6g}"


def build_figure(q: ChartQuery, candles: Sequence[Candle],
                 volumes: Optional[Sequence[Tuple[int, float]]] = None,
                 source_label: str = "Data: CoinGecko") -> go.Figure:
    t = THEMES[q.theme]
    has_rsi = any(k == "rsi" for k, _ in q.indicators)
    rows = 1 + (1 if volumes else 0) + (1 if has_rsi else 0)
    heights = [0.62] + ([0.18] if volumes else []) + ([0.2] if has_rsi else [])
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.035,
                        row_heights=[h / sum(heights) for h in heights])
    x = [datetime.fromtimestamp(c.ts_ms / 1000, tz=UTC) for c in candles]
    closes = [c.close for c in candles]
    fig.add_trace(go.Candlestick(
        x=x, open=[c.open for c in candles], high=[c.high for c in candles],
        low=[c.low for c in candles], close=closes, name="price",
        increasing=dict(line=dict(color=t.up, width=1), fillcolor=t.up),
        decreasing=dict(line=dict(color=t.down, width=1), fillcolor=t.down),
        whiskerwidth=0.4, showlegend=False,
    ), row=1, col=1)

    palette = iter(t.lines)
    for kind, period in q.indicators:
        if kind == "rsi":
            continue
        series = ind.sma(closes, period) if kind == "sma" else ind.ema(closes, period)
        label = f"{kind.upper()} {period}"
        if all(v is None for v in series):
            label += f" (needs {period} candles)"
        fig.add_trace(go.Scatter(x=x, y=series, mode="lines", name=label,
                                 line=dict(color=next(palette, t.muted), width=1.6)), row=1, col=1)

    row = 2
    if volumes:
        fig.add_trace(go.Scatter(
            x=[datetime.fromtimestamp(ts / 1000, tz=UTC) for ts, _ in volumes],
            y=[v for _, v in volumes], mode="lines", name="24h volume", fill="tozeroy",
            line=dict(color=t.volume, width=1), showlegend=False,
        ), row=row, col=1)
        fig.update_yaxes(title_text="24h vol", row=row, col=1)
        row += 1
    if has_rsi:
        period = next(p for k, p in q.indicators if k == "rsi")
        fig.add_trace(go.Scatter(x=x, y=ind.rsi(closes, period), mode="lines", name=f"RSI {period}",
                                 line=dict(color=t.rsi, width=1.4), showlegend=False), row=row, col=1)
        for level in (30, 70):
            fig.add_hline(y=level, line=dict(color=t.grid, width=1, dash="dot"), row=row, col=1)
        fig.update_yaxes(range=[0, 100], tickvals=[30, 70], title_text=f"RSI {period}", row=row, col=1)

    first, last = closes[0], closes[-1]
    change = (last - first) / first * 100 if first else 0.0
    color = t.up if change >= 0 else t.down
    span = f"{q.days}D"
    title = (f"<b>{q.coin.upper()}</b> / {q.vs.upper()}  <span style='color:{t.muted}'>{span}</span>"
             f"   <b>{_fmt_price(last)}</b>  <span style='color:{color}'>{change:+.2f}%</span>")
    fig.update_layout(
        title=dict(text=title, x=0.012, xanchor="left", y=0.975, font=dict(size=18)),
        paper_bgcolor=t.paper, plot_bgcolor=t.plot,
        font=dict(family=FONT, color=t.text, size=12),
        margin=dict(l=56, r=24, t=56, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom",
                    bgcolor="rgba(0,0,0,0)", font=dict(color=t.muted)),
        showlegend=any(k != "rsi" for k, _ in q.indicators),
    )
    fig.update_xaxes(gridcolor=t.grid, zeroline=False, showline=False, rangeslider_visible=False,
                     tickfont=dict(color=t.muted))
    fig.update_yaxes(gridcolor=t.grid, zeroline=False, showline=False, tickfont=dict(color=t.muted),
                     title_font=dict(color=t.muted, size=11))
    fig.add_annotation(text=source_label, xref="paper", yref="paper", x=1, y=-0.06, xanchor="right",
                       showarrow=False, font=dict(size=10, color=t.muted))
    return fig


class Renderer:
    """Serialises Kaleido calls: its export process is shared per worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def render(self, q: ChartQuery, candles: Sequence[Candle],
               volumes: Optional[Sequence[Tuple[int, float]]] = None,
               source_label: str = "Data: CoinGecko") -> bytes:
        fig = build_figure(q, candles, volumes, source_label)
        with self._lock:
            return fig.to_image(format=q.fmt, width=q.width, height=q.height, scale=q.scale, engine="kaleido")


def summary(candles: Sequence[Candle]) -> Dict[str, float]:
    closes: List[float] = [c.close for c in candles]
    return {
        "first_close": closes[0],
        "last_close": closes[-1],
        "change_pct": (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0.0,
        "high": max(c.high for c in candles),
        "low": min(c.low for c in candles),
    }
