"""OpenAPI 3.1 description, served at /openapi.json and checked against the routes in tests."""

from __future__ import annotations

from typing import Any, Dict

from . import __version__
from .validation import DAYS, FORMATS, HEIGHT, MAX_INDICATORS, THEMES, WIDTH

ERROR = {"$ref": "#/components/responses/Error"}
ENVELOPE_JSON = {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}}
INDICATOR_PATTERN = rf"^((sma|ema|rsi):\d{{1,3}})(,(sma|ema|rsi):\d{{1,3}}){{0,{MAX_INDICATORS - 1}}}$"


def _param(name: str, schema: Dict[str, Any], description: str) -> Dict[str, Any]:
    return {"name": name, "in": "query", "required": False, "schema": schema, "description": description}


DATA_PARAMS = [
    _param("coin", {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,79}$", "default": "bitcoin"},
           "CoinGecko coin id (see /coins/list on CoinGecko). The server default is configurable."),
    _param("vs", {"type": "string", "pattern": "^[a-z]{2,10}$", "default": "usd"}, "Quote currency."),
    _param("days", {"type": "integer", "enum": list(DAYS), "default": 30},
           "Range. Candles are 30 min for 1 day, 4 h up to 30 days, 4 days beyond."),
]

CHART_PARAMS = DATA_PARAMS + [
    _param("format", {"type": "string", "enum": list(FORMATS), "default": "png"}, "Image format."),
    _param("theme", {"type": "string", "enum": list(THEMES), "default": "dark"}, "Colour theme."),
    _param("width", {"type": "integer", "minimum": WIDTH[0], "maximum": WIDTH[1], "default": WIDTH[2]},
           "Width in CSS pixels."),
    _param("height", {"type": "integer", "minimum": HEIGHT[0], "maximum": HEIGHT[1], "default": HEIGHT[2]},
           "Height in CSS pixels."),
    _param("scale", {"type": "integer", "enum": [1, 2], "default": 1}, "Pixel density (2 for retina)."),
    _param("indicators", {"type": "string", "pattern": INDICATOR_PATTERN, "example": "sma:20,ema:50,rsi:14"},
           f"Up to {MAX_INDICATORS} of sma:N, ema:N (overlays) and one rsi:N (panel); N = 2..200."),
    _param("volume", {"type": "boolean", "default": False},
           "Add a panel with CoinGecko's rolling 24h volume (one extra upstream call)."),
]

COMMON_ERRORS = {"400": ERROR, "404": ERROR, "429": ERROR, "502": ERROR, "503": ERROR}


def spec() -> Dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "CoinGecko chart service",
            "version": __version__,
            "description": "Renders candlestick charts from CoinGecko OHLC data. Responses that are "
                           "not images use the envelope {success, data, error, meta}.",
            "license": {"name": "MIT", "identifier": "MIT"},
        },
        "paths": {
            "/health": {"get": {
                "summary": "Liveness and upstream circuit state",
                "responses": {"200": {"description": "Service is up",
                                      "content": ENVELOPE_JSON}},
            }},
            "/v1/chart": {"get": {
                "summary": "Candlestick chart image",
                "parameters": CHART_PARAMS,
                "responses": {
                    "200": {
                        "description": "The chart. X-Cache tells whether market data came from cache "
                                       "(HIT), upstream (MISS) or an expired cache entry while upstream "
                                       "was down (STALE).",
                        "headers": {"X-Cache": {"schema": {"type": "string", "enum": ["HIT", "MISS", "STALE"]}},
                                    "X-Request-ID": {"schema": {"type": "string"}}},
                        "content": {"image/png": {}, "image/svg+xml": {}},
                    },
                    **COMMON_ERRORS,
                },
            }},
            "/v1/ohlc": {"get": {
                "summary": "Candles as JSON (same data the chart uses)",
                "parameters": DATA_PARAMS,
                "responses": {"200": {"description": "Candles",
                                      "content": ENVELOPE_JSON},
                              **COMMON_ERRORS},
            }},
            "/openapi.json": {"get": {"summary": "This document",
                                      "responses": {"200": {"description": "OpenAPI document"}}}},
        },
        "components": {
            "schemas": {
                "Envelope": {
                    "type": "object",
                    "required": ["success", "data", "error", "meta"],
                    "properties": {
                        "success": {"type": "boolean"},
                        "data": {},
                        "error": {"oneOf": [{"type": "null"}, {"$ref": "#/components/schemas/Error"}]},
                        "meta": {"type": "object"},
                    },
                },
                "Error": {
                    "type": "object",
                    "required": ["code", "message", "details"],
                    "properties": {"code": {"type": "string", "examples": ["invalid_parameter"]},
                                   "message": {"type": "string"}, "details": {"type": "object"}},
                },
            },
            "responses": {"Error": {"description": "Error envelope",
                                    "content": ENVELOPE_JSON}},
        },
    }
