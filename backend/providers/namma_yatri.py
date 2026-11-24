"""Independent Namma Yatri / ONDC Beckn BAP quote fetcher and metadata.

Namma Yatri operates on the open-source MovingTech/Beckn stack over ONDC. Live
queries require an authorized ONDC Buyer App (BAP) gateway endpoint or authorized
token; unauthenticated direct calls return UNAVAILABLE.
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
    "id": "namma-yatri",
    "name": "Namma Yatri",
    "status": "estimated",
    "details": (
        "Uses live ONDC Buyer App (BAP) quotes when registered; otherwise shows "
        "calibrated city meter/rate-card estimates from OpenStreetMap route distance."
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
    rides = [ride for ride in RIDE_OPTIONS if ride["provider"] == "Namma Yatri"]
    bap_url = env.get("NAMMA_YATRI_BAP_SEARCH_URL", "").strip()
    token = env.get("NAMMA_YATRI_AUTH_TOKEN", "").strip()

    if not bap_url:
        return [
            unavailable_quote(
                ride,
                "Namma Yatri ONDC Buyer App gateway is not configured; open Namma Yatri directly to check your fare.",
            )
            for ride in rides
        ]

    if not coordinates_available(pickup, drop):
        return [
            unavailable_quote(
                ride,
                "Pickup and destination coordinates are required for ONDC/Namma Yatri quotes.",
            )
            for ride in rides
        ]

    try:
        validated_url = validate_base_url(env, "NAMMA_YATRI_BAP_SEARCH_URL", bap_url)
    except ValueError as error:
        return [unavailable_quote(ride, str(error)) for ride in rides]

    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "origin": {"lat": pickup["lat"], "lng": pickup["lng"]},
        "destination": {"lat": drop["lat"], "lng": drop["lng"]},
    }
    return fetch_standard_json_provider(
        "Namma Yatri",
        validated_url,
        headers,
        rides,
        method="POST",
        payload=payload,
        requester=requester,
    )
