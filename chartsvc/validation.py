"""Strict query-string parsing. Unknown or malformed parameters are a 400."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Set, Tuple

from .config import Settings
from .errors import ApiError

DAYS = (1, 7, 14, 30, 90, 180, 365)
FORMATS = ("png", "svg")
THEMES = ("dark", "light")
WIDTH = (320, 1600, 1200)     # min, max, default (CSS pixels)
HEIGHT = (240, 1200, 675)
SCALES = (1, 2)
MAX_INDICATORS = 4
PERIOD = (2, 200)

_COIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_VS_RE = re.compile(r"^[a-z]{2,10}$")
_IND_RE = re.compile(r"^(sma|ema|rsi):(\d{1,3})$")


@dataclass(frozen=True)
class DataQuery:
    coin: str
    vs: str
    days: int


@dataclass(frozen=True)
class ChartQuery(DataQuery):
    fmt: str = "png"
    theme: str = "dark"
    width: int = WIDTH[2]
    height: int = HEIGHT[2]
    scale: int = 1
    indicators: Tuple[Tuple[str, int], ...] = ()
    volume: bool = False

    @property
    def cache_key(self) -> tuple:
        return (self.coin, self.vs, self.days, self.fmt, self.theme, self.width, self.height,
                self.scale, self.indicators, self.volume)


def _bad(param: str, message: str, allowed: Optional[object] = None) -> ApiError:
    details = {"param": param}
    if allowed is not None:
        details["allowed"] = allowed
    return ApiError(400, "invalid_parameter", message, details)


def _one(args: Mapping[str, str], name: str) -> Optional[str]:
    getlist = getattr(args, "getlist", None)
    values = getlist(name) if getlist else ([args[name]] if name in args else [])
    if len(values) > 1:
        raise _bad(name, f"'{name}' was given more than once.")
    return values[0].strip() if values else None


def _int_in(args: Mapping[str, str], name: str, lo: int, hi: int, default: int) -> int:
    raw = _one(args, name)
    if raw is None or raw == "":
        return default
    if not raw.isdigit():
        raise _bad(name, f"'{name}' must be a whole number.")
    value = int(raw)
    if not lo <= value <= hi:
        raise _bad(name, f"'{name}' must be between {lo} and {hi}.", [lo, hi])
    return value


def _check_unknown(args: Mapping[str, str], allowed: Set[str]) -> None:
    unknown = sorted(set(args.keys()) - allowed)
    if unknown:
        raise _bad(unknown[0], f"Unknown parameter '{unknown[0]}'.", sorted(allowed))


def parse_data_query(args: Mapping[str, str], settings: Settings, extra: Set[str] = frozenset()) -> DataQuery:
    _check_unknown(args, {"coin", "vs", "days"} | set(extra))
    coin = (_one(args, "coin") or settings.default_coin).lower()
    if not _COIN_RE.match(coin):
        raise _bad("coin", "'coin' must be a CoinGecko coin id such as 'bitcoin' or 'ethereum'.")
    if settings.allowed_coins and coin not in settings.allowed_coins:
        raise _bad("coin", "This coin is not enabled on this server.", list(settings.allowed_coins))
    vs = (_one(args, "vs") or "usd").lower()
    if not _VS_RE.match(vs):
        raise _bad("vs", "'vs' must be a currency code such as 'usd' or 'eur'.")
    raw_days = _one(args, "days") or "30"
    if not raw_days.isdigit() or int(raw_days) not in DAYS:
        raise _bad("days", "'days' must be one of the values CoinGecko supports.", list(DAYS))
    return DataQuery(coin, vs, int(raw_days))


def parse_indicators(raw: Optional[str]) -> Tuple[Tuple[str, int], ...]:
    if not raw:
        return ()
    items = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if len(items) > MAX_INDICATORS:
        raise _bad("indicators", f"At most {MAX_INDICATORS} indicators.")
    out = []
    for item in items:
        m = _IND_RE.match(item)
        if not m:
            raise _bad("indicators", "Use kind:period, e.g. 'sma:20,ema:50,rsi:14'.", ["sma", "ema", "rsi"])
        period = int(m.group(2))
        if not PERIOD[0] <= period <= PERIOD[1]:
            raise _bad("indicators", f"Indicator periods must be between {PERIOD[0]} and {PERIOD[1]}.")
        if (m.group(1), period) not in out:
            out.append((m.group(1), period))
    if sum(1 for k, _ in out if k == "rsi") > 1:
        raise _bad("indicators", "Only one RSI per chart.")
    return tuple(out)


def _bool(args: Mapping[str, str], name: str) -> bool:
    raw = (_one(args, name) or "false").lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    raise _bad(name, f"'{name}' must be true or false.")


def parse_chart_query(args: Mapping[str, str], settings: Settings) -> ChartQuery:
    extra = {"format", "theme", "width", "height", "scale", "indicators", "volume"}
    base = parse_data_query(args, settings, extra)
    fmt = (_one(args, "format") or "png").lower()
    if fmt not in FORMATS:
        raise _bad("format", "'format' must be png or svg.", list(FORMATS))
    theme = (_one(args, "theme") or "dark").lower()
    if theme not in THEMES:
        raise _bad("theme", "'theme' must be dark or light.", list(THEMES))
    scale = _int_in(args, "scale", 1, 2, 1)
    return ChartQuery(
        coin=base.coin, vs=base.vs, days=base.days, fmt=fmt, theme=theme,
        width=_int_in(args, "width", WIDTH[0], WIDTH[1], WIDTH[2]),
        height=_int_in(args, "height", HEIGHT[0], HEIGHT[1], HEIGHT[2]),
        scale=scale,
        indicators=parse_indicators(_one(args, "indicators")),
        volume=_bool(args, "volume"),
    )
