"""Route validation, metric sanitization, and genuine quote comparison engine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

CATEGORIES = {"bike", "auto", "sedan", "premium"}
SORT_OPTIONS = {"cheapest", "pickup", "best_value"}
GENUINE_QUOTE_TYPES = {"LIVE_QUOTE", "FARE_ESTIMATE"}
GENUINE_STATUSES = {"live", "estimated"}
MAX_KM = 500
MAX_MINUTES = 24 * 60


class InvalidRoute(ValueError):
    pass


def parse_metrics(value: Any) -> dict[str, float] | None:
    """Validate {'distance_km','duration_minutes'} from a client value, or None if absent."""
    if value is None:
        return None
    try:
        km = float(value["distance_km"])
        minutes = float(value["duration_minutes"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Route metrics must include distance_km and duration_minutes.")
    if not (0 < km <= MAX_KM) or not (0 < minutes <= MAX_MINUTES):
        raise ValueError("Route distance or duration is out of range.")
    return {"distance_km": round(km, 1), "duration_minutes": round(minutes)}


def validate_route(pickup: Any, destination: Any) -> tuple[str, str]:
    if not isinstance(pickup, str) or not isinstance(destination, str):
        raise InvalidRoute("Pickup and destination must be text.")
    pickup = " ".join(pickup.split())
    destination = " ".join(destination.split())
    if not pickup or not destination:
        raise InvalidRoute("Enter both a pickup and destination.")
    if len(pickup) > 160 or len(destination) > 160:
        raise InvalidRoute("Locations must be 160 characters or fewer.")
    if pickup.casefold() == destination.casefold():
        raise InvalidRoute("Pickup and destination must be different.")
    return pickup, destination


def _is_comparable_quote(ride: dict[str, Any]) -> bool:
    quote_type = ride.get("quoteType")
    if quote_type is not None and quote_type not in GENUINE_QUOTE_TYPES:
        return False
    fare = ride.get("fare")
    return (
        ride.get("availability_status") == "available"
        and isinstance(fare, (int, float))
        and not isinstance(fare, bool)
        and fare >= 0
        and bool(ride.get("currency"))
        and ride.get("fare_status") in GENUINE_STATUSES
    )


def compare_rides(
    pickup: str,
    destination: str,
    rides: list[dict[str, Any]],
    category: str = "all",
    sort: str = "cheapest",
) -> dict[str, Any]:
    pickup, destination = validate_route(pickup, destination)
    if category != "all" and category not in CATEGORIES:
        raise ValueError("Unsupported ride category.")
    if sort not in SORT_OPTIONS:
        raise ValueError("Unsupported sort option.")

    unique: dict[str, dict[str, Any]] = {}
    for ride in rides:
        if category != "all" and ride.get("ride_type") != category:
            continue
        provider = str(ride.get("provider", "")).casefold()
        ride_type = str(ride.get("ride_type", "")).casefold()
        key = str(ride.get("id") or f"{provider}:{ride_type}")
        if provider and ride_type:
            unique.setdefault(key, dict(ride))

    results = list(unique.values())
    comparable = [ride for ride in results if _is_comparable_quote(ride)]
    lowest_ids = set()
    bases = {(ride["currency"], ride["fare_status"]) for ride in comparable}
    for currency, status in bases:
        same_basis = [
            ride for ride in comparable
            if ride["currency"] == currency and ride["fare_status"] == status
        ]
        if len(same_basis) >= 2:
            lowest = min(same_basis, key=lambda ride: ride["fare"])
            lowest_ids.add(lowest.get("id"))

    if sort == "cheapest":
        results.sort(
            key=lambda ride: (
                ride.get("fare") is None,
                ride["fare"] if ride.get("fare") is not None else float("inf"),
            )
        )
    elif sort == "pickup":
        results.sort(
            key=lambda ride: (
                ride.get("pickup_eta_minutes") is None,
                ride.get("pickup_eta_minutes") if ride.get("pickup_eta_minutes") is not None else float("inf"),
            )
        )
    else:
        results.sort(
            key=lambda ride: (
                ride.get("fare") is None or ride.get("trip_duration_minutes") is None,
                (ride["fare"] if ride.get("fare") is not None else float("inf"))
                / max(ride.get("trip_duration_minutes") or 1, 1),
            )
        )

    for ride in results:
        ride["is_lowest"] = ride.get("id") in lowest_ids

    sources = {ride.get("fare_status") for ride in results if _is_comparable_quote(ride)}
    fare_source = next(iter(sources)) if len(sources) == 1 else "mixed" if sources else "unavailable"

    cheapest_quote = None
    if comparable:
        cheapest = min(comparable, key=lambda ride: ride["fare"])
        cheapest_quote = {
            "id": cheapest.get("id"),
            "provider": cheapest.get("provider"),
            "vehicleType": cheapest.get("vehicleType") or cheapest.get("product_name"),
            "fare": cheapest.get("fare"),
            "fareRange": cheapest.get("fareRange"),
            "currency": cheapest.get("currency"),
            "quoteType": cheapest.get("quoteType") or (
                "LIVE_QUOTE" if cheapest.get("fare_status") == "live" else "FARE_ESTIMATE"
            ),
            "quoteSource": cheapest.get("quoteSource"),
        }

    return {
        "route": {"pickup": pickup, "destination": destination},
        "rides": results,
        "cheapest_quote": cheapest_quote,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "fare_source": fare_source,
    }
