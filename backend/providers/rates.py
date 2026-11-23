"""Indian city rate cards for clearly labelled route-based INR estimates.

Calibrated from government-notified city RTA tariffs (Bengaluru, Delhi, Mumbai,
Hyderabad, Chennai) and open-source Indian ride-hailing pricing formulas
(nammayatri/nammayatri, sreeharshitha864/ola-fare-estimator, Mahesh-Chandrasekar/SmartChoice).
These are transparent route estimates, never live provider quotes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Default/Bengaluru card tuple:
# (provider, vehicle, ride_type, base_fare, included_km, per_km, per_minute, minimum_fare, rate_multiplier)
RATE_CARDS = [
    ("Rapido", "Bike taxi", "bike", 20, 1, 7.5, 0.5, 25, 1.00),
    ("Rapido", "Auto", "auto", 34, 2, 17.0, 0.3, 35, 1.04),
    ("Rapido", "Rapido Cab", "sedan", 55, 2, 15.5, 1.2, 75, 0.98),
    ("Namma Yatri", "Auto", "auto", 36, 2, 18.0, 0.0, 36, 1.00),
    ("Namma Yatri", "Mini / Sedan", "sedan", 58, 2, 16.0, 1.2, 78, 0.96),
    ("Namma Yatri", "XL Cab", "premium", 88, 2, 21.0, 1.8, 120, 0.97),
]

# City-specific overrides keyed by (provider, ride_type) -> (base, included_km, per_km, per_min, min_fare, multiplier)
CITY_RATE_OVERRIDES: dict[str, dict[tuple[str, str], tuple[float, float, float, float, float, float]]] = {
    "bengaluru": {},
    "mumbai": {
        ("Rapido", "bike"): (20, 1, 7.0, 0.4, 25, 1.00),
        ("Rapido", "auto"): (27, 1.5, 18.22, 0.0, 27, 1.03),
        ("Namma Yatri", "auto"): (27, 1.5, 18.22, 0.0, 27, 1.00),
        ("Rapido", "sedan"): (38, 1.5, 21.0, 1.1, 60, 0.98),
        ("Namma Yatri", "sedan"): (40, 1.5, 21.90, 1.1, 65, 0.97),
        ("Namma Yatri", "premium"): (65, 1.5, 26.0, 1.6, 100, 0.98),
    },
    "delhi": {
        ("Rapido", "bike"): (15, 1, 6.0, 0.4, 20, 1.00),
        ("Rapido", "auto"): (30, 1.5, 11.0, 0.2, 30, 1.04),
        ("Namma Yatri", "auto"): (30, 1.5, 11.0, 0.0, 30, 1.00),
        ("Rapido", "sedan"): (45, 1.5, 14.0, 1.0, 65, 0.98),
        ("Namma Yatri", "sedan"): (48, 1.5, 14.5, 1.0, 68, 0.96),
        ("Namma Yatri", "premium"): (75, 1.5, 19.0, 1.5, 110, 0.97),
    },
    "hyderabad": {
        ("Rapido", "bike"): (18, 1, 6.5, 0.4, 22, 1.00),
        ("Rapido", "auto"): (30, 1.6, 14.0, 0.2, 30, 1.04),
        ("Namma Yatri", "auto"): (30, 1.6, 14.0, 0.0, 30, 1.00),
        ("Rapido", "sedan"): (50, 2.0, 14.5, 1.0, 70, 0.98),
        ("Namma Yatri", "sedan"): (52, 2.0, 15.0, 1.0, 72, 0.96),
        ("Namma Yatri", "premium"): (80, 2.0, 20.0, 1.5, 115, 0.97),
    },
    "chennai": {
        ("Rapido", "bike"): (18, 1, 6.5, 0.4, 22, 1.00),
        ("Rapido", "auto"): (30, 1.8, 15.0, 0.2, 30, 1.04),
        ("Namma Yatri", "auto"): (30, 1.8, 15.0, 0.0, 30, 1.00),
        ("Rapido", "sedan"): (50, 2.0, 15.0, 1.0, 70, 0.98),
        ("Namma Yatri", "sedan"): (52, 2.0, 15.5, 1.0, 72, 0.96),
        ("Namma Yatri", "premium"): (82, 2.0, 20.0, 1.5, 115, 0.97),
    },
}

CITY_BOUNDS: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("bengaluru", "Bengaluru", 12.75, 13.25, 77.35, 77.85),
    ("mumbai", "Mumbai MMR", 18.85, 19.35, 72.70, 73.15),
    ("delhi", "Delhi NCR", 28.35, 28.90, 76.85, 77.55),
    ("hyderabad", "Hyderabad", 17.15, 17.65, 78.20, 78.70),
    ("chennai", "Chennai", 12.85, 13.25, 80.05, 80.35),
)

CITY_NIGHT_RULES: dict[str, tuple[tuple[int, ...], float]] = {
    "bengaluru": ((22, 23, 0, 1, 2, 3, 4), 1.50),
    "hyderabad": ((23, 0, 1, 2, 3, 4), 1.50),
    "delhi": ((23, 0, 1, 2, 3, 4), 1.25),
    "mumbai": ((0, 1, 2, 3, 4), 1.25),
    "chennai": ((23, 0, 1, 2, 3, 4), 1.25),
}

# Typical platform fee/aggregator variance when estimating Uber & Ola without live API credentials.
PROVIDER_MULTIPLIERS = {
    "Uber": 1.05,
    "Ola": 1.02,
}

LOW_FACTOR = 0.90
HIGH_FACTOR = 1.20
IST = timezone(timedelta(hours=5, minutes=30))


def detect_city(pickup: dict[str, Any] | None) -> tuple[str, str]:
    """Return (city_key, display_name) from pickup coordinates, defaulting to Bengaluru/India."""
    if pickup and pickup.get("lat") is not None and pickup.get("lng") is not None:
        try:
            lat, lng = float(pickup["lat"]), float(pickup["lng"])
            for key, label, min_lat, max_lat, min_lng, max_lng in CITY_BOUNDS:
                if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                    return key, label
        except (TypeError, ValueError):
            pass
    return "bengaluru", "Standard India"


def city_rate_cards(city_key: str) -> list[tuple[str, str, str, float, float, float, float, float, float]]:
    overrides = CITY_RATE_OVERRIDES.get(city_key, {})
    cards = []
    for provider, vehicle, ride_type, base, inc, per_km, per_min, minimum, mult in RATE_CARDS:
        override = overrides.get((provider, ride_type))
        if override:
            b, i, k, m, mn, ml = override
            cards.append((provider, vehicle, ride_type, b, i, k, m, mn, ml))
        else:
            cards.append((provider, vehicle, ride_type, base, inc, per_km, per_min, minimum, mult))
    return cards


def time_factor(city_key: str, provider: str, ride_type: str, now_ist: datetime | None = None) -> tuple[float, str]:
    """Return (multiplier, period_label) based on IST time-of-day and city RTA night rules."""
    current = now_ist or datetime.now(timezone.utc).astimezone(IST)
    hour = current.hour
    night_hours, auto_night_mult = CITY_NIGHT_RULES.get(city_key, ((23, 0, 1, 2, 3, 4), 1.25))
    if hour in night_hours:
        # Metered autos follow RTA night multipliers; app cabs/bikes carry lighter night demand.
        mult = auto_night_mult if ride_type == "auto" else 1.15
        return mult, "night tariff"
    if hour in (8, 9, 10, 17, 18, 19, 20):
        # Zero-commission Namma Yatri autos adhere more closely to metered RTA slabs in peak hours.
        if provider == "Namma Yatri" and ride_type == "auto":
            return 1.00, "peak hours (RTA base)"
        return 1.12, "peak-hour demand"
    return 1.00, "off-peak"
