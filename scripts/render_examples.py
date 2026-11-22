"""Render the README example images from synthetic candles (no network).

    python scripts/render_examples.py
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chartsvc.coingecko import parse_ohlc, parse_volumes  # noqa: E402
from chartsvc.render import Renderer  # noqa: E402
from chartsvc.validation import ChartQuery  # noqa: E402

OUT = ROOT / "docs" / "media"
LABEL = "Synthetic data for illustration"
T0 = 1_772_582_400_000


def synthetic(n: int, step_ms: int, start: float, seed: int):
    rng = random.Random(seed)  # noqa: S311 - reproducible fake prices
    rows, vols, price = [], [], start
    for i in range(n):
        o = price
        drift = 0.0025 * math.sin(i / 9) + 0.0008
        c = max(0.01, o * (1 + rng.gauss(drift, 0.011)))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        rows.append([T0 + i * step_ms, o, h, lo, c])
        vols.append([T0 + i * step_ms, 4e8 * (1 + 0.6 * abs(c - o) / o * 60 + 0.3 * math.sin(i / 7))])
        price = c
    return parse_ohlc(rows), parse_volumes({"total_volumes": vols})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    r = Renderer()
    candles, volumes = synthetic(180, 4 * 3_600_000, 2400.0, seed=11)
    dark = ChartQuery("example-coin", "usd", 30, width=1200, height=675,
                      indicators=(("sma", 20), ("ema", 50)), volume=True)
    (OUT / "chart-dark.png").write_bytes(r.render(dark, candles, volumes, LABEL))
    candles, _ = synthetic(90, 4 * 86_400_000, 0.84, seed=5)
    light = ChartQuery("example-coin", "eur", 365, theme="light", width=1200, height=675,
                       indicators=(("ema", 20), ("rsi", 14)))
    (OUT / "chart-light.png").write_bytes(r.render(light, candles, None, LABEL))
    svg = ChartQuery("example-coin", "usd", 30, fmt="svg", width=900, height=420)
    (OUT / "chart.svg").write_bytes(r.render(svg, candles[-60:], None, LABEL))
    for p in sorted(OUT.iterdir()):
        print(p.relative_to(ROOT), p.stat().st_size // 1024, "KiB")


if __name__ == "__main__":
    main()
