"""Shared normalization, validation, and HTTP helpers for cab fare providers."""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

HTTP_TIMEOUT_SECONDS = 5
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_AMOUNT_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


class ProviderRequestError(Exception):
    """Raised when an external provider HTTP or JSON response fails."""

    def __init__(self, status_code: int | None = None, invalid_response: bool = False):
        self.status_code = status_code
        self.invalid_response = invalid_response
        super().__init__("Provider fare request failed.")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def coordinates_available(pickup: dict[str, Any] | None, drop: dict[str, Any] | None) -> bool:
    return bool(
        pickup
        and drop
        and pickup.get("lat") is not None
        and pickup.get("lng") is not None
        and drop.get("lat") is not None
        and drop.get("lng") is not None
    )


def validate_base_url(env: Mapping[str, str], key: str, default: str) -> str:
    """Return sanitized base URL, requiring HTTPS except on local loopback test hosts."""
    raw = env.get(key, default).strip().rstrip("/") or default
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme == "https" and host:
        return raw
    if parsed.scheme == "http" and host in {"127.0.0.1", "localhost", "::1"}:
        return raw
    raise ValueError(f"{key} must use HTTPS.")


def request_json(
    url: str,
    headers: dict[str, str],
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> Any:
    body_bytes: bytes | None = None
    req_headers = dict(headers)
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    try:
        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise ProviderRequestError(status_code=error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ProviderRequestError() from None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProviderRequestError(invalid_response=True) from None


def failure_reason(error: ProviderRequestError, provider: str) -> str:
    if error.status_code in (401, 403):
        return f"{provider} rejected credentials or the session expired; re-authorize on backend."
    if error.status_code == 429:
        return f"{provider} rate limit reached. Try again later."
    if error.invalid_response:
        return f"{provider} returned an invalid fare response."
    if error.status_code is not None:
        return f"{provider} fare request failed (HTTP {error.status_code})."
    return f"{provider} fare endpoint is timed out or unreachable."


def unavailable_quote(
    ride: dict[str, Any],
    reason: str,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Build a strictly honest UNAVAILABLE item with zero synthetic prices."""
    timestamp = retrieved_at or now_iso()
    return {
        **ride,
        "vehicleType": ride["product_name"],
        "fare": None,
        "fareRange": None,
        "fare_low": None,
        "fare_high": None,
        "currency": None,
        "etaMinutes": None,
        "pickup_eta_minutes": None,
        "trip_duration_minutes": None,
        "distance_km": None,
        "quoteType": "UNAVAILABLE",
        "retrievedAt": timestamp,
        "status": "unavailable",
        "error": reason,
        "fare_status": "unavailable",
        "availability_status": "unknown",
        "fare_unavailable_reason": reason,
        "fare_disclaimer": "Genuine quote unavailable; check live price inside the official provider app.",
    }


def _nested_number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("amount"))
    if isinstance(value, (int, float, Decimal)):
        try:
            num = Decimal(str(value))
        except InvalidOperation:
            return None
        return num if num.is_finite() and num >= 0 else None
    if isinstance(value, str):
        matches = _AMOUNT_PATTERN.findall(value.replace(",", ""))
        if not matches:
            return None
        try:
            nums = [Decimal(match) for match in matches]
        except InvalidOperation:
            return None
        return min(nums) if len(nums) == 1 else nums[0]
    return None


def _numbers_from_estimate(value: Any) -> list[Decimal]:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        num = _nested_number(value)
        return [num] if num is not None else []
    if not isinstance(value, str):
        return []
    matches = _AMOUNT_PATTERN.findall(value.replace(",", ""))
    try:
        return [Decimal(match) for match in matches]
    except InvalidOperation:
        return []


def ride_type_for(name: str) -> str:
    normalized = name.casefold()
    if any(word in normalized for word in ("bike", "moto", "scooty", "scooter", "cycle")):
        return "bike"
    if any(word in normalized for word in ("auto", "rickshaw", "tuk")):
        return "auto"
    if any(word in normalized for word in ("premium", "black", "luxury", "xl", "suv", "priority")):
        return "premium"
    return "sedan"


def extract_products(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("prices", "products", "estimates", "ride_estimates", "categories", "quotes", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "response", "result", "catalog"):
        if key in payload:
            found = extract_products(payload[key])
            if found:
                return found
    return []


def _parse_eta_minutes(product: dict[str, Any]) -> int | None:
    for key in ("etaMinutes", "eta_minutes", "pickup_eta_minutes", "pickup_eta_min", "eta"):
        val = product.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            return round(val)
        if isinstance(val, str):
            matches = _AMOUNT_PATTERN.findall(val)
            if matches:
                return round(float(matches[0]))
    for sec_key in ("pickup_estimate", "estimatedPickupDuration"):
        sec = product.get(sec_key)
        if isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec >= 0:
            return max(1, round(sec / 60))
    return None


def _parse_trip_duration_minutes(product: dict[str, Any]) -> int | None:
    dur = product.get("duration")
    if isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > 0:
        return max(1, round(dur / 60)) if dur > 90 else round(dur)
    return None


def normalize_quote(
    provider: str,
    product: dict[str, Any],
    index: int,
    retrieved_at: str | None = None,
) -> dict[str, Any] | None:
    """Parse a genuine provider payload entry into unified CabCompare + standard fields."""
    name = next(
        (
            product[key].strip()
            for key in (
                "localized_display_name",
                "display_name",
                "serviceName",
                "vehicleVariant",
                "vehicleType",
                "name",
                "category",
                "product_name",
            )
            if isinstance(product.get(key), str) and product[key].strip()
        ),
        "Ride",
    )

    currency = product.get("currency_code", product.get("currency"))
    fare_obj = product.get("fare")
    if isinstance(fare_obj, dict):
        currency = currency or fare_obj.get("currency_code", fare_obj.get("currency"))
    if not isinstance(currency, str) or not _CURRENCY_PATTERN.fullmatch(currency.strip().upper()):
        return None
    currency = currency.strip().upper()

    low = next(
        (
            _nested_number(product[key])
            for key in ("low_estimate", "fare_low", "fare_min", "min_fare", "minFare", "min_price", "low")
            if key in product and _nested_number(product[key]) is not None
        ),
        None,
    )
    high = next(
        (
            _nested_number(product[key])
            for key in ("high_estimate", "fare_high", "fare_max", "max_fare", "maxFare", "max_price", "high")
            if key in product and _nested_number(product[key]) is not None
        ),
        None,
    )

    fare_range_obj = product.get("fareRange")
    if isinstance(fare_range_obj, dict):
        low = low if low is not None else _nested_number(fare_range_obj.get("min", fare_range_obj.get("minFare")))
        high = high if high is not None else _nested_number(fare_range_obj.get("max", fare_range_obj.get("maxFare")))

    estimate_val = next(
        (
            product[key]
            for key in ("total_fare", "totalFare", "fare", "price", "estimatedFare", "fare_estimate", "estimate", "amount")
            if key in product
        ),
        None,
    )
    estimate_nums = _numbers_from_estimate(estimate_val)

    if low is None and high is None and estimate_nums:
        low, high = min(estimate_nums), max(estimate_nums)
    elif low is None:
        low = high
    elif high is None:
        high = low
    if low is None or high is None or low > high:
        return None

    low_val, high_val = float(low), float(high)
    if not math.isfinite(low_val) or not math.isfinite(high_val):
        return None

    is_range = low_val != high_val or str(product.get("fare_kind", "")).casefold() == "estimate"
    quote_type = "FARE_ESTIMATE" if is_range else "LIVE_QUOTE"
    fare_status = "estimated" if is_range else "live"
    eta_minutes = _parse_eta_minutes(product)
    trip_duration = _parse_trip_duration_minutes(product)
    surge = _nested_number(product.get("surge_multiplier"))

    if quote_type == "LIVE_QUOTE":
        disclaimer = f"Live upfront quote from {provider}."
    else:
        disclaimer = f"{provider} API estimate range; final fare depends on driver assignment & demand."
    if surge is not None and surge > 1:
        disclaimer += f" Includes {surge:g}x surge."

    timestamp = retrieved_at or now_iso()
    fare_value = round((low_val + high_val) / 2, 2) if low_val != high_val else low_val
    return {
        "id": f"{provider.lower().replace(' ', '-')}-{product.get('product_id', index)}",
        "provider": provider,
        "vehicleType": name,
        "product_name": name,
        "ride_type": ride_type_for(name),
        "fare": fare_value,
        "fareRange": {"min": low_val, "max": high_val},
        "fare_low": low_val,
        "fare_high": high_val,
        "currency": currency,
        "etaMinutes": eta_minutes,
        "pickup_eta_minutes": eta_minutes,
        "trip_duration_minutes": trip_duration,
        "distance_km": None,
        "quoteType": quote_type,
        "retrievedAt": timestamp,
        "status": "success",
        "error": None,
        "fare_status": fare_status,
        "availability_status": "available",
        "fare_disclaimer": disclaimer,
    }


def fetch_standard_json_provider(
    provider: str,
    url: str,
    headers: dict[str, str],
    fallback_rides: list[dict[str, Any]],
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    requester: Any = request_json,
) -> list[dict[str, Any]]:
    timestamp = now_iso()
    try:
        data = requester(url, headers, method=method, payload=payload)
    except ProviderRequestError as error:
        reason = failure_reason(error, provider)
        return [unavailable_quote(ride, reason, timestamp) for ride in fallback_rides]

    quotes = [
        quote
        for index, product in enumerate(extract_products(data))
        if (quote := normalize_quote(provider, product, index, retrieved_at=timestamp)) is not None
    ]
    if quotes:
        return quotes
    return [
        unavailable_quote(
            ride,
            f"{provider} returned no priced products with a valid currency.",
            timestamp,
        )
        for ride in fallback_rides
    ]
