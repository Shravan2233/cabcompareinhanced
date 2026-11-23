"""Independent Ola quote fetcher and provider metadata.

Requires invite-only partner X-APP-TOKEN (OLA_APP_TOKEN) or authorized session
bearer token. Never generates synthetic replacement fares when unconfigured.
"""
from __future__ import annotations

import os
import urllib.parse
from collections.abc import Mapping
from typing import Any

from .base import (
    coordinates_available,
    fetch_standard_json_provider,
    request_json,
    unavailable_quote,
    validate_base_url,
)
from .options import RIDE_OPTIONS

PROVIDER = {
    "id": "ola",
    "name": "Ola",
    "status": "hybrid",
    "details": (
        "Uses live Ola API quotes when authorized partner credentials exist; "
        "otherwise shows calibrated city rate-card estimates from OpenStreetMap route distance."
    ),
    "booking_url": None,
}


def fetch_quotes(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    env: Mapping[str, str] | None = None,
    *,
    requester: Any = request_json,
) -> list[dict[str, Any]]:
    env = os.environ if env is None else env
    rides = [ride for ride in RIDE_OPTIONS if ride["provider"] == "Ola"]
    app_token = env.get("OLA_APP_TOKEN", "").strip()
    bearer_token = env.get("OLA_BEARER_TOKEN", "").strip()

    if not (app_token or bearer_token):
        return [
            unavailable_quote(
                ride,
                "Ola partner fare API access is not configured; open Ola directly with your route prefilled.",
            )
            for ride in rides
        ]

    if not coordinates_available(pickup, drop):
        return [
            unavailable_quote(ride, "Pickup and destination coordinates are required for Ola quotes.")
            for ride in rides
        ]

    try:
        base = validate_base_url(env, "OLA_API_BASE_URL", "https://devapi.olacabs.com")
    except ValueError as error:
        return [unavailable_quote(ride, str(error)) for ride in rides]

    params = urllib.parse.urlencode({
        "pickup_lat": pickup["lat"],
        "pickup_lng": pickup["lng"],
        "drop_lat": drop["lat"],
        "drop_lng": drop["lng"],
        "service_type": "p2p",
    })
    headers: dict[str, str] = {"Accept": "application/json"}
    if app_token:
        headers["X-APP-TOKEN"] = app_token
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    return fetch_standard_json_provider(
        "Ola",
        f"{base}/v1/products?{params}",
        headers,
        rides,
        requester=requester,
    )
