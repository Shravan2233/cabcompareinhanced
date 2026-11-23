"""Independent Rapido quote fetcher and provider metadata.

Rapido does not provide a public unauthenticated fare API. Live quotes require an
explicitly authorized corporate/partner gateway URL and token via environment
variables; otherwise every option returns UNAVAILABLE honestly.
"""
from __future__ import annotations

import os
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
    "id": "rapido",
    "name": "Rapido",
    "status": "estimated",
    "details": (
        "Uses authorized gateway quotes when configured; otherwise shows calibrated "
        "city rate-card estimates from OpenStreetMap route distance."
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
    rides = [ride for ride in RIDE_OPTIONS if ride["provider"] == "Rapido"]
    gateway_url = env.get("RAPIDO_API_URL", "").strip()
    token = env.get("RAPIDO_AUTH_TOKEN", "").strip()

    if not (gateway_url and token):
        return [
            unavailable_quote(
                ride,
                "Rapido has no public unauthenticated fare API (requires an OTP user session or "
                "authorized corporate gateway). Open Rapido to check your live fare.",
            )
            for ride in rides
        ]

    if not coordinates_available(pickup, drop):
        return [
            unavailable_quote(ride, "Pickup and destination coordinates are required for Rapido quotes.")
            for ride in rides
        ]

    try:
        validated_url = validate_base_url(env, "RAPIDO_API_URL", gateway_url)
    except ValueError as error:
        return [unavailable_quote(ride, str(error)) for ride in rides]

    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    device_id = env.get("RAPIDO_DEVICE_ID", "").strip()
    if device_id:
        headers["deviceid"] = device_id

    payload = {
        "pickup": {"lat": pickup["lat"], "lng": pickup["lng"]},
        "drop": {"lat": drop["lat"], "lng": drop["lng"]},
    }
    return fetch_standard_json_provider(
        "Rapido",
        validated_url,
        headers,
        rides,
        method="POST",
        payload=payload,
        requester=requester,
    )
