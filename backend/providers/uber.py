"""Independent Uber quote fetcher and provider metadata.

Requires official Uber credentials (UBER_OAUTH_TOKEN or legacy UBER_SERVER_TOKEN)
AND written comparison approval (UBER_COMPARISON_APPROVED=true). Never generates
mock or distance-formula replacement fares.
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
    "id": "uber",
    "name": "Uber",
    "status": "hybrid",
    "details": (
        "Uses live Uber API quotes when authorized credentials and approval exist; "
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
    rides = [ride for ride in RIDE_OPTIONS if ride["provider"] == "Uber"]
    oauth_token = env.get("UBER_OAUTH_TOKEN", "").strip()
    server_token = env.get("UBER_SERVER_TOKEN", "").strip()

    if not (oauth_token or server_token):
        return [
            unavailable_quote(
                ride,
                "Uber live fare API access is not configured; open Uber directly with your route prefilled.",
            )
            for ride in rides
        ]

    if env.get("UBER_COMPARISON_APPROVED", "").strip().casefold() != "true":
        return [
            unavailable_quote(
                ride,
                "Written Uber approval for competitor fare comparisons is required; set "
                "UBER_COMPARISON_APPROVED=true only after that approval.",
            )
            for ride in rides
        ]

    if not coordinates_available(pickup, drop):
        return [
            unavailable_quote(ride, "Pickup and destination coordinates are required for Uber quotes.")
            for ride in rides
        ]

    try:
        base = validate_base_url(env, "UBER_API_BASE_URL", "https://api.uber.com")
    except ValueError as error:
        return [unavailable_quote(ride, str(error)) for ride in rides]

    params = urllib.parse.urlencode({
        "start_latitude": pickup["lat"],
        "start_longitude": pickup["lng"],
        "end_latitude": drop["lat"],
        "end_longitude": drop["lng"],
    })
    auth_header = f"Bearer {oauth_token}" if oauth_token else f"Token {server_token}"
    return fetch_standard_json_provider(
        "Uber",
        f"{base}/v1.2/estimates/price?{params}",
        {"Authorization": auth_header, "Accept": "application/json"},
        rides,
        requester=requester,
    )
