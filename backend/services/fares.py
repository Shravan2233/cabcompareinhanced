"""Concurrent fare aggregation across providers with calibrated city rate-card fallback.

Queries all independent provider modules first for genuine API / ONDC quotes. Whenever a
provider option has no authorized live quote and OpenStreetMap/OSRM route metrics exist,
returns a transparently labeled city rate-card FARE_ESTIMATE (never labeled as a live
provider quote). Returns UNAVAILABLE only when route distance cannot be determined.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..providers import namma_yatri, ola, rapido, uber
from ..providers.base import ProviderRequestError  # noqa: F401 - re-exported for callers/tests
from ..providers.options import RIDE_OPTIONS
from ..providers.rates import estimate_option_fare
from .guards import QuoteTTLCache

_CREDENTIAL_FINGERPRINT_KEYS = (
    "UBER_OAUTH_TOKEN",
    "UBER_SERVER_TOKEN",
    "UBER_API_BASE_URL",
    "UBER_COMPARISON_APPROVED",
    "OLA_APP_TOKEN",
    "OLA_BEARER_TOKEN",
    "OLA_API_BASE_URL",
    "RAPIDO_API_URL",
    "RAPIDO_AUTH_TOKEN",
    "RAPIDO_DEVICE_ID",
    "NAMMA_YATRI_BAP_SEARCH_URL",
    "NAMMA_YATRI_AUTH_TOKEN",
)

_quote_cache = QuoteTTLCache(ttl_seconds=float(os.getenv("QUOTE_CACHE_TTL_SECONDS", "45")))


def uber_fares(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    return uber.fetch_quotes(pickup, drop, env)


def ola_fares(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    return ola.fetch_quotes(pickup, drop, env)


def clear_quote_cache() -> None:
    _quote_cache.reset()


def comparison_rides(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    metrics: dict[str, float] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve live provider quotes first, filling missing options with city rate-card estimates."""
    active_env = os.environ if env is None else env
    live_by_provider_and_type: dict[tuple[str, str], list[dict[str, Any]]] = {}

    cache_key = None
    cached_api: list[dict[str, Any]] | None = None
    if env is None:
        fingerprint = _quote_cache.env_fingerprint(active_env, _CREDENTIAL_FINGERPRINT_KEYS)
        cache_key = _quote_cache.build_key(pickup, drop, fingerprint)
        cached_api = _quote_cache.get(cache_key)

    if cached_api is not None:
        raw_api_rides = cached_api
    else:
        fetchers = (uber_fares, ola_fares, rapido.fetch_quotes, namma_yatri.fetch_quotes)
        with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
            futures = [pool.submit(fn, pickup, drop, active_env) for fn in fetchers]
            raw_api_rides = []
            for future in futures:
                raw_api_rides.extend(future.result())
        if cache_key is not None:
            _quote_cache.set(cache_key, raw_api_rides)

    for ride in raw_api_rides:
        if ride.get("status") == "success" and ride.get("quoteType") in {"LIVE_QUOTE", "FARE_ESTIMATE"}:
            ride.setdefault("quoteSource", "provider_api")
            key = (ride["provider"], ride["ride_type"])
            live_by_provider_and_type.setdefault(key, []).append(ride)

    # Preserve extra live API products first, then backfill unquoted options with city rate cards.
    resolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for rides_group in live_by_provider_and_type.values():
        for ride in rides_group:
            if ride["id"] not in seen_ids:
                seen_ids.add(ride["id"])
                resolved.append(ride)

    unavailable_lookup = {
        (ride["provider"], ride["ride_type"]): ride
        for ride in raw_api_rides
        if ride.get("quoteType") == "UNAVAILABLE"
    }

    for option in RIDE_OPTIONS:
        key = (option["provider"], option["ride_type"])
        if key in live_by_provider_and_type:
            continue
        if metrics:
            est = estimate_option_fare(option, metrics, pickup)
            if est["id"] not in seen_ids:
                seen_ids.add(est["id"])
                resolved.append(est)
        else:
            fallback_unavail = unavailable_lookup.get(key)
            if fallback_unavail and fallback_unavail["id"] not in seen_ids:
                seen_ids.add(fallback_unavail["id"])
                resolved.append(fallback_unavail)

    return resolved
