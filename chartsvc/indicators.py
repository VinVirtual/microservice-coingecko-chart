"""Technical indicators over a list of closing prices. ``None`` = not enough data yet."""

from __future__ import annotations

from typing import List, Optional, Sequence

Series = List[Optional[float]]


def sma(values: Sequence[float], period: int) -> Series:
    if period < 1:
        raise ValueError("period must be >= 1")
    out: Series = []
    window = 0.0
    for i, v in enumerate(values):
        window += v
        if i >= period:
            window -= values[i - period]
        out.append(window / period if i >= period - 1 else None)
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """Exponential moving average seeded with the SMA of the first ``period`` values."""
    if period < 1:
        raise ValueError("period must be >= 1")
    out: Series = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """Wilder's RSI (0-100)."""
    if period < 1:
        raise ValueError("period must be >= 1")
    out: Series = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period

    def value(g: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / loss)

    out[period] = value(avg_g, avg_l)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = value(avg_g, avg_l)
    return out
