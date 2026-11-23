from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from ..providers.options import RIDE_OPTIONS
from .estimates import estimate_rides, provider_rate_card_estimate_rides

HTTP_TIMEOUT_SECONDS = 8
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_AMOUNT_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


class ProviderRequestError(Exception):
    def __init__(self, status_code: int | None = None, invalid_response: bool = False):
        self.status_code = status_code
        self.invalid_response = invalid_response
        super().__init__("Provider fare request failed.")


def _get_json(url: str, headers: dict[str, str]) -> Any:
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise ProviderRequestError(status_code=error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ProviderRequestError() from None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProviderRequestError(invalid_response=True) from None


def _coordinates_available(pickup: dict[str, Any] | None, drop: dict[str, Any] | None) -> bool:
    return bool(pickup and drop and all(key in pickup for key in ("lat", "lng"))
                and all(key in drop for key in ("lat", "lng")))


def _unavailable(ride: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **ride,
        "fare": None,
        "fare_low": None,
        "fare_high": None,
        "currency": None,
        "fare_status": "unavailable",
        "availability_status": "unknown",
        "fare_unavailable_reason": reason,
        "fare_disclaimer": "Fare and availability are not confirmed; check the provider app.",
    }


def _request_failure_reason(error: ProviderRequestError, provider: str) -> str:
    if error.status_code in (401, 403):
        return f"{provider} rejected the configured credentials or API access."
    if error.status_code == 429:
        return f"{provider} fare API rate limit reached. Try again later."
    if error.invalid_response:
        return f"{provider} returned an invalid fare response."
    if error.status_code is not None:
        return f"{provider} fare API request failed (HTTP {error.status_code})."
    return f"{provider} fare API is temporarily unreachable."


def _nested_number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("amount"))
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        return number if number.is_finite() and number >= 0 else None
    if isinstance(value, str):
        matches = _AMOUNT_PATTERN.findall(value.replace(",", ""))
        if not matches:
            return None
        try:
            numbers = [Decimal(match) for match in matches]
        except InvalidOperation:
            return None
        return min(numbers) if len(numbers) == 1 else numbers[0]
    return None


def _numbers_from_estimate(value: Any) -> list[Decimal]:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = _nested_number(value)
        return [number] if number is not None else []
    if not isinstance(value, str):
        return []
    matches = _AMOUNT_PATTERN.findall(value.replace(",", ""))
    try:
        return [Decimal(match) for match in matches]
    except InvalidOperation:
        return []


def _ride_type(name: str) -> str:
    normalized = name.casefold()
    if any(word in normalized for word in ("bike", "moto", "scooter", "cycle")):
        return "bike"
    if any(word in normalized for word in ("auto", "rickshaw", "tuk")):
        return "auto"
    if any(word in normalized for word in ("premium", "black", "luxury", "xl", "suv")):
        return "premium"
    return "sedan"


def _products(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("prices", "products", "estimates", "ride_estimates", "categories"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "response", "result"):
        if key in payload:
            found = _products(payload[key])
            if found:
                return found
    return []


def _quote_product(provider: str, product: dict[str, Any], index: int) -> dict[str, Any] | None:
    name = next(
        (product[key] for key in ("localized_display_name", "display_name", "name", "category", "product_name")
         if isinstance(product.get(key), str) and product[key].strip()),
        "Ride",
    )
    currency = product.get("currency_code", product.get("currency"))
    fare_object = product.get("fare")
    if isinstance(fare_object, dict):
        currency = currency or fare_object.get("currency_code", fare_object.get("currency"))
    if not isinstance(currency, str) or not _CURRENCY_PATTERN.fullmatch(currency.upper()):
        return None
    currency = currency.upper()

    low = next((_nested_number(product[key]) for key in ("low_estimate", "fare_low", "fare_min", "min_fare", "low")
                if key in product and _nested_number(product[key]) is not None), None)
    high = next((_nested_number(product[key]) for key in ("high_estimate", "fare_high", "fare_max", "max_fare", "high")
                 if key in product and _nested_number(product[key]) is not None), None)
    estimate_value = next((product[key] for key in ("estimate", "fare_estimate", "fare", "price", "amount")
                           if key in product), None)
    estimate_numbers = _numbers_from_estimate(estimate_value)

    if low is None and high is None and estimate_numbers:
        low, high = min(estimate_numbers), max(estimate_numbers)
    elif low is None:
        low = high
    elif high is None:
        high = low
    if low is None or high is None or low > high:
        return None

    low_value, high_value = float(low), float(high)
    if not math.isfinite(low_value) or not math.isfinite(high_value):
        return None
    surge = _nested_number(product.get("surge_multiplier"))
    disclaimer = f"{provider} API estimate; availability is not guaranteed. Confirm the fare in the provider app."
    if surge is not None and surge > 1:
        disclaimer += f" The returned estimate includes a surge multiplier of {surge:g}."
    return {
        "id": f"{provider.lower().replace(' ', '-')}-{product.get('product_id', index)}",
        "provider": provider,
        "product_name": name,
        "ride_type": _ride_type(name),
        "fare": (low_value + high_value) / 2,
        "fare_low": low_value,
        "fare_high": high_value,
        "currency": currency,
        "fare_status": "live",
        "availability_status": "unknown",
        "pickup_eta_minutes": None,
        "trip_duration_minutes": None,
        "distance_km": None,
        "fare_disclaimer": disclaimer,
    }


def _configured_base(env: Mapping[str, str], key: str, default: str) -> str:
    return env.get(key, default).strip().rstrip("/")


def _fetch_provider(
    provider: str,
    url: str,
    headers: dict[str, str],
    rides: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        payload = _get_json(url, headers)
    except ProviderRequestError as error:
        reason = _request_failure_reason(error, provider)
        return [_unavailable(ride, reason) for ride in rides]
    quotes = [
        quote
        for index, product in enumerate(_products(payload))
        if (quote := _quote_product(provider, product, index)) is not None
    ]
    if quotes:
        return quotes
    return [_unavailable(ride, f"{provider} returned no priced products with a valid currency.") for ride in rides]


def uber_fares(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    env = os.environ if env is None else env
    rides = [ride for ride in RIDE_OPTIONS if ride["provider"] == "Uber"]
    token = env.get("UBER_SERVER_TOKEN", "").strip()
    if not token:
        return [_unavailable(ride, "UBER_SERVER_TOKEN is not configured.") for ride in rides]
    if env.get("UBER_COMPARISON_APPROVED", "").strip().casefold() != "true":
        return [
            _unavailable(
                ride,
                "Written Uber approval for competitor fare comparisons is required; set "
                "UBER_COMPARISON_APPROVED=true only after that approval.",
            )
            for ride in rides
        ]
    if not _coordinates_available(pickup, drop):
        return [_unavailable(ride, "Select pickup and destination with coordinates to request an estimate.") for ride in rides]

    params = urllib.parse.urlencode({
        "start_latitude": pickup["lat"],
        "start_longitude": pickup["lng"],
        "end_latitude": drop["lat"],
        "end_longitude": drop["lng"],
    })
    base = _configured_base(env, "UBER_API_BASE_URL", "https://api.uber.com")
    return _fetch_provider(
        "Uber",
        f"{base}/v1.2/estimates/price?{params}",
        {"Authorization": f"Token {token}", "Accept": "application/json"},
        rides,
    )


def ola_fares(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    env = os.environ if env is None else env
    rides = [ride for ride in RIDE_OPTIONS if ride["provider"] == "Ola"]
    token = env.get("OLA_APP_TOKEN", "").strip()
    if not token:
        return [_unavailable(ride, "OLA_APP_TOKEN is not configured.") for ride in rides]
    if not _coordinates_available(pickup, drop):
        return [_unavailable(ride, "Select pickup and destination with coordinates to request an estimate.") for ride in rides]

    params = urllib.parse.urlencode({
        "pickup_lat": pickup["lat"],
        "pickup_lng": pickup["lng"],
        "drop_lat": drop["lat"],
        "drop_lng": drop["lng"],
        "service_type": "p2p",
    })
    base = _configured_base(env, "OLA_API_BASE_URL", "https://devapi.olacabs.com")
    return _fetch_provider(
        "Ola",
        f"{base}/v1/products?{params}",
        {"X-APP-TOKEN": token, "Accept": "application/json"},
        rides,
    )


def comparison_rides(
    pickup: dict[str, Any] | None,
    drop: dict[str, Any] | None,
    metrics: dict[str, float] | None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    api_rides = uber_fares(pickup, drop, env) + ola_fares(pickup, drop, env)
    if metrics:
        estimates = estimate_rides(metrics, pickup, drop)
        rides = [ride for ride in api_rides if ride["fare_status"] == "live"]
        rides.extend(ride for ride in estimates if ride["provider"] not in {"Uber", "Ola"})
        uncovered_api_options = []
        for provider in ("Uber", "Ola"):
            live_types = {
                ride["ride_type"]
                for ride in rides
                if ride["provider"] == provider and ride["fare_status"] == "live"
            }
            fallback_rides = provider_rate_card_estimate_rides(provider, metrics, live_types, pickup)
            covered_types = live_types | {ride["ride_type"] for ride in fallback_rides}
            rides.extend(fallback_rides)
            uncovered_api_options.extend(
                ride for ride in api_rides
                if ride["provider"] == provider
                and ride["fare_status"] == "unavailable"
                and ride["ride_type"] not in covered_types
            )
        rides.extend(uncovered_api_options)
    else:
        rides = api_rides + [
            _unavailable(
                ride,
                "Route distance and duration are unavailable; select a mapped route or try again.",
            )
            for ride in RIDE_OPTIONS
            if ride["provider"] in ("Rapido", "Namma Yatri")
        ]
    return rides
