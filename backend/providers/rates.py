"""Calibrated Indian city rate-card estimates using OSRM road distance and IST time bands.

These are transparent route estimates (never disguised as live provider API quotes),
giving riders realistic city tariff ranges when direct provider APIs are unauthenticated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .base import now_iso

IST = timezone(timedelta(hours=5, minutes=30))

# City bounding boxes: (city_id, display_name, min_lat, max_lat, min_lng, max_lng)
_CITY_BOXES: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("bengaluru", "Bengaluru", 12.75, 13.25, 77.35, 77.85),
    ("mumbai", "Mumbai", 18.85, 19.35, 72.75, 73.15),
    ("delhi", "Delhi NCR", 28.35, 28.90, 76.85, 77.45),
    ("hyderabad", "Hyderabad", 17.20, 17.65, 78.20, 78.70),
    ("chennai", "Chennai", 12.85, 13.30, 80.05, 80.35),
)

# (base_fare, base_km, per_km, per_min, min_fare, low_factor, high_factor)
_DEFAULT_TARIFFS: dict[str, tuple[float, float, float, float, float, float, float]] = {
    "bike": (20.0, 2.0, 9.0, 0.75, 25.0, 0.90, 1.12),
    "auto": (30.0, 2.0, 15.0, 1.50, 35.0, 0.92, 1.18),
    "sedan": (75.0, 4.0, 18.0, 2.00, 85.0, 0.92, 1.18),
    "premium": (115.0, 4.0, 24.0, 2.50, 130.0, 0.92, 1.20),
}

_CITY_TARIFF_OVERRIDES: dict[str, dict[str, tuple[float, float, float, float, float, float, float]]] = {
    "bengaluru": {
        # Matches Bengaluru BTP Auto (₹30 for 2km + ₹15/km) and Karnataka aggregator cab slabs
        "bike": (20.0, 2.0, 9.0, 0.75, 25.0, 0.90, 1.14),
        "auto": (30.0, 2.0, 15.0, 1.65, 35.0, 0.94, 1.22),
        "sedan": (75.0, 4.0, 18.5, 2.10, 89.0, 0.92, 1.19),
        "premium": (115.0, 4.0, 24.5, 2.60, 135.0, 0.92, 1.22),
    },
    "mumbai": {
        "bike": (20.0, 1.5, 8.5, 0.75, 25.0, 0.90, 1.14),
        "auto": (26.0, 1.5, 17.14, 1.60, 26.0, 0.94, 1.18),
        "sedan": (70.0, 3.0, 19.5, 2.20, 85.0, 0.92, 1.20),
        "premium": (110.0, 3.0, 26.0, 2.80, 130.0, 0.92, 1.22),
    },
    "delhi": {
        "bike": (18.0, 2.0, 7.5, 0.65, 22.0, 0.90, 1.12),
        "auto": (30.0, 1.5, 11.0, 1.20, 30.0, 0.93, 1.18),
        "sedan": (65.0, 3.0, 16.0, 1.80, 75.0, 0.92, 1.18),
        "premium": (105.0, 3.0, 22.0, 2.40, 120.0, 0.92, 1.20),
    },
    "hyderabad": {
        "bike": (18.0, 2.0, 8.0, 0.65, 22.0, 0.90, 1.12),
        "auto": (28.0, 1.6, 13.0, 1.30, 30.0, 0.92, 1.18),
        "sedan": (70.0, 4.0, 17.0, 1.90, 80.0, 0.92, 1.18),
        "premium": (110.0, 4.0, 23.0, 2.40, 125.0, 0.92, 1.20),
    },
    "chennai": {
        "bike": (18.0, 2.0, 8.0, 0.70, 24.0, 0.90, 1.14),
        "auto": (35.0, 1.8, 14.5, 1.40, 35.0, 0.93, 1.20),
        "sedan": (72.0, 4.0, 17.5, 1.90, 82.0, 0.92, 1.18),
        "premium": (110.0, 4.0, 23.5, 2.50, 125.0, 0.92, 1.20),
    },
}

_PROVIDER_FACTORS: dict[tuple[str, str], float] = {
    ("Rapido", "bike"): 0.94,
    ("Uber", "bike"): 1.00,
    ("Ola", "bike"): 1.04,
    ("Namma Yatri", "auto"): 0.97,
    ("Rapido", "auto"): 1.00,
    ("Uber", "auto"): 1.04,
    ("Ola", "auto"): 1.07,
    ("Rapido", "sedan"): 0.97,
    ("Namma Yatri", "sedan"): 0.99,
    ("Uber", "sedan"): 1.05,
    ("Ola", "sedan"): 1.10,
    ("Namma Yatri", "premium"): 0.98,
    ("Uber", "premium"): 1.06,
    ("Ola", "premium"): 1.12,
}


def detect_city(pickup: dict[str, Any] | None) -> tuple[str, str]:
    if not pickup or pickup.get("lat") is None or pickup.get("lng") is None:
        return "india", "India standard"
    lat, lng = float(pickup["lat"]), float(pickup["lng"])
    for city_id, label, min_lat, max_lat, min_lng, max_lng in _CITY_BOXES:
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            return city_id, label
    return "india", "India standard"


def time_factor_and_label(now: datetime | None = None) -> tuple[float, str]:
    current = (now or datetime.now(timezone.utc)).astimezone(IST)
    minutes = current.hour * 60 + current.minute
    if 8 * 60 <= minutes < 11 * 60:
        return 1.12, "morning peak"
    if 17 * 60 + 30 <= minutes < 21 * 60 + 30:
        return 1.15, "evening peak"
    if minutes >= 23 * 60 or minutes < 5 * 60:
        return 1.25, "night tariff"
    return 1.00, "standard hours"


def estimate_option_fare(
    option: dict[str, Any],
    metrics: dict[str, float],
    pickup: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Compute a calibrated rate-card estimate range for one ride option."""
    city_id, city_label = detect_city(pickup)
    ride_type = option["ride_type"]
    provider = option["provider"]

    tariffs = _CITY_TARIFF_OVERRIDES.get(city_id, _DEFAULT_TARIFFS)
    base, base_km, per_km, per_min, min_fare, low_factor, high_factor = tariffs.get(
        ride_type,
        _DEFAULT_TARIFFS["sedan"],
    )

    distance_km = float(metrics["distance_km"])
    duration_min = float(metrics["duration_minutes"])
    extra_km = max(0.0, distance_km - base_km)
    raw = max(min_fare, base + extra_km * per_km + duration_min * per_min)

    t_factor, time_label = time_factor_and_label(now)
    p_factor = _PROVIDER_FACTORS.get((provider, ride_type), 1.0)
    mid = round(raw * t_factor * p_factor)
    low = max(round(min_fare * 0.9), round(mid * low_factor))
    high = max(low + 5, round(mid * high_factor))
    mid = round((low + high) / 2)

    timestamp = retrieved_at or now_iso()
    note = (
        f"{city_label} {time_label} rate-card estimate "
        f"({distance_km:g} km road route, ~{round(duration_min)} min). "
        f"Confirm live surge and promos in {provider}."
    )
    return {
        "id": option["id"],
        "provider": provider,
        "vehicleType": option["product_name"],
        "product_name": option["product_name"],
        "ride_type": ride_type,
        "fare": float(mid),
        "fareRange": {"min": float(low), "max": float(high)},
        "fare_low": float(low),
        "fare_high": float(high),
        "currency": "INR",
        "etaMinutes": None,
        "pickup_eta_minutes": None,
        "trip_duration_minutes": round(duration_min),
        "distance_km": round(distance_km, 1),
        "quoteType": "FARE_ESTIMATE",
        "quoteSource": "rate_card",
        "retrievedAt": timestamp,
        "status": "success",
        "error": None,
        "fare_status": "estimated",
        "availability_status": "available",
        "fare_disclaimer": note,
    }
