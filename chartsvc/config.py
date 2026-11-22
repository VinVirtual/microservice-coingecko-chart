"""Settings from environment variables (12-factor). Validated once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

PUBLIC_BASE = "https://api.coingecko.com/api/v3"
PRO_BASE = "https://pro-api.coingecko.com/api/v3"


class ConfigError(ValueError):
    """Raised at startup when an environment variable is invalid."""


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _float(env: Mapping[str, str], name: str, default: float, lo: float, hi: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _csv(env: Mapping[str, str], name: str) -> Tuple[str, ...]:
    return tuple(p.strip() for p in env.get(name, "").split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    # Upstream
    api_key: Optional[str] = None
    api_plan: str = "public"          # public (no key) | demo | pro
    connect_timeout: float = 3.05
    read_timeout: float = 10.0
    retries: int = 2
    breaker_failures: int = 5
    breaker_reset_seconds: float = 60.0
    # Cache
    cache_ttl_seconds: int = 300
    stale_ttl_seconds: int = 3600
    cache_max_entries: int = 256
    image_cache_max_bytes: int = 64 * 1024 * 1024
    # Requests
    default_coin: str = "bitcoin"
    allowed_coins: Tuple[str, ...] = ()
    rate_limit_chart: str = "20 per minute"
    rate_limit_data: str = "60 per minute"
    rate_limit_storage_uri: str = "memory://"
    trusted_proxies: int = 0
    cors_origins: Tuple[str, ...] = ()
    log_level: str = "INFO"

    @property
    def base_url(self) -> str:
        return PRO_BASE if self.api_plan == "pro" else PUBLIC_BASE

    @property
    def auth_header(self) -> Optional[Tuple[str, str]]:
        if not self.api_key:
            return None
        return ("x-cg-pro-api-key" if self.api_plan == "pro" else "x-cg-demo-api-key", self.api_key)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> Settings:
        env = os.environ if env is None else env
        key = env.get("COINGECKO_API_KEY", "").strip() or None
        plan = env.get("COINGECKO_API_PLAN", "demo" if key else "public").strip().lower()
        if plan not in {"public", "demo", "pro"}:
            raise ConfigError("COINGECKO_API_PLAN must be public, demo or pro")
        if plan in {"demo", "pro"} and not key:
            raise ConfigError(f"COINGECKO_API_PLAN={plan} needs COINGECKO_API_KEY")
        level = env.get("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ConfigError("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        return cls(
            api_key=key,
            api_plan=plan,
            connect_timeout=_float(env, "UPSTREAM_CONNECT_TIMEOUT", 3.05, 0.5, 30),
            read_timeout=_float(env, "UPSTREAM_READ_TIMEOUT", 10.0, 1, 60),
            retries=_int(env, "UPSTREAM_RETRIES", 2, 0, 5),
            breaker_failures=_int(env, "BREAKER_FAILURES", 5, 1, 100),
            breaker_reset_seconds=_float(env, "BREAKER_RESET_SECONDS", 60.0, 1, 3600),
            cache_ttl_seconds=_int(env, "CACHE_TTL_SECONDS", 300, 0, 86400),
            stale_ttl_seconds=_int(env, "STALE_TTL_SECONDS", 3600, 0, 7 * 86400),
            cache_max_entries=_int(env, "CACHE_MAX_ENTRIES", 256, 1, 100_000),
            image_cache_max_bytes=_int(env, "IMAGE_CACHE_MAX_MB", 64, 0, 4096) * 1024 * 1024,
            default_coin=env.get("DEFAULT_COIN", "bitcoin").strip().lower() or "bitcoin",
            allowed_coins=tuple(c.lower() for c in _csv(env, "ALLOWED_COINS")),
            rate_limit_chart=env.get("RATE_LIMIT_CHART", "20 per minute"),
            rate_limit_data=env.get("RATE_LIMIT_DATA", "60 per minute"),
            rate_limit_storage_uri=env.get("RATE_LIMIT_STORAGE_URI", "memory://"),
            trusted_proxies=_int(env, "TRUSTED_PROXIES", 0, 0, 5),
            cors_origins=_csv(env, "CORS_ORIGINS"),
            log_level=level,
        )
