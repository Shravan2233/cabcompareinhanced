from __future__ import annotations

import logging
import math
import pickle
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ..models.schema import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERICAL_FEATURES,
    current_time_of_day,
)
from ..providers.options import RIDE_OPTIONS
from ..providers.rates import (
    HIGH_FACTOR,
    LOW_FACTOR,
    PROVIDER_MULTIPLIERS,
    city_rate_cards,
    detect_city,
    time_factor,
)

MAX_KM = 500
MAX_MINUTES = 24 * 60
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "fare_model.joblib"
logger = logging.getLogger(__name__)
RATE_CARD_DISCLAIMER = (
    "Rate-card estimate from route distance and duration; actual fares may vary with demand, "
    "surge, traffic, tolls, and provider pricing. Confirm in the app."
)


def parse_metrics(value: Any) -> dict[str, float] | None:
    """Validate {'distance_km','duration_minutes'} from a client value. None if absent."""
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


def load_fare_model(model_path: Path = MODEL_PATH) -> dict[str, Any] | None:
    """Load a trusted local artifact, returning None when it is absent or invalid."""
    if not model_path.is_file():
        return None
    try:
        artifact = joblib.load(model_path)
    except (OSError, EOFError, ValueError, TypeError, ImportError, AttributeError, pickle.UnpicklingError) as error:
        logger.warning("Could not load fare model at %s: %s", model_path, error)
        return None
    if (
        not isinstance(artifact, dict)
        or artifact.get("format_version") != 1
        or artifact.get("feature_columns") != list(FEATURE_COLUMNS)
        or not isinstance(artifact.get("currency"), str)
        or not isinstance(artifact.get("feature_categories"), dict)
        or not callable(getattr(artifact.get("model"), "predict", None))
    ):
        logger.warning("Fare model at %s has an unsupported artifact format.", model_path)
        return None
    return artifact


def _coordinate(place: dict[str, Any] | None, key: str) -> float:
    if not place or place.get(key) is None:
        return float("nan")
    try:
        value = float(place[key])
    except (TypeError, ValueError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def model_estimate_rides(
    metrics: dict[str, float],
    pickup: dict[str, Any] | None = None,
    drop: dict[str, Any] | None = None,
    model_path: Path = MODEL_PATH,
) -> list[dict[str, Any]]:
    artifact = load_fare_model(model_path)
    if artifact is None:
        return []

    time_of_day = current_time_of_day()
    currency = artifact["currency"].upper()
    categories = artifact["feature_categories"]
    feature_rows = []
    ride_options = []
    for ride in RIDE_OPTIONS:
        feature = {
            "provider": ride["provider"].casefold(),
            "vehicle": ride["product_name"].casefold(),
            "time_of_day": time_of_day,
            "currency": currency,
            "distance_km": metrics["distance_km"],
            "duration_minutes": metrics["duration_minutes"],
            "pickup_lat": _coordinate(pickup, "lat"),
            "pickup_lng": _coordinate(pickup, "lng"),
            "destination_lat": _coordinate(drop, "lat"),
            "destination_lng": _coordinate(drop, "lng"),
        }
        if any(feature[key] not in categories.get(key, []) for key in CATEGORICAL_FEATURES):
            continue
        feature_rows.append(feature)
        ride_options.append(ride)

    if not feature_rows:
        return []

    try:
        predictions = np.asarray(artifact["model"].predict(pd.DataFrame(feature_rows, columns=FEATURE_COLUMNS)), dtype=float)
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        logger.warning("Fare model prediction failed; using route-rate fallback: %s", error)
        return []
    if predictions.ndim != 1 or len(predictions) != len(ride_options) or not np.isfinite(predictions).all():
        logger.warning("Fare model returned invalid predictions; using route-rate fallback.")
        return []
    if (predictions <= 0).any():
        logger.warning("Fare model returned a non-positive fare; using route-rate fallback.")
        return []

    return [
        {
            "id": f"{ride['id']}-model",
            "provider": ride["provider"],
            "product_name": ride["product_name"],
            "ride_type": ride["ride_type"],
            "fare": round(float(prediction)),
            "fare_low": None,
            "fare_high": None,
            "currency": currency,
            "fare_status": "model",
            "availability_status": "unknown",
            "pickup_eta_minutes": None,
            "trip_duration_minutes": metrics["duration_minutes"],
            "distance_km": metrics["distance_km"],
            "fare_disclaimer": (
                "Prediction from a trained model using historical labeled fares; not a provider quote. "
                "Actual fare and availability can differ. Confirm in the provider app."
            ),
        }
        for ride, prediction in zip(ride_options, predictions)
    ]


def rate_card_estimate_rides(
    metrics: dict[str, float],
    pickup: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Estimate Rapido and Namma Yatri fares from city rate cards; never present them as live."""
    km, minutes = metrics["distance_km"], metrics["duration_minutes"]
    city_key, city_label = detect_city(pickup)
    cards = city_rate_cards(city_key)
    rides = []
    for provider, vehicle, ride_type, base, included_km, per_km, per_minute, minimum, multiplier in cards:
        t_mult, period_label = time_factor(city_key, provider, ride_type)
        raw_fare = (base + per_km * max(km - included_km, 0) + per_minute * minutes) * multiplier * t_mult
        fare = round(max(minimum, raw_fare))
        rides.append({
            "id": f"{provider.lower().replace(' ', '-')}-{ride_type}-estimate",
            "provider": provider,
            "product_name": vehicle,
            "ride_type": ride_type,
            "fare": fare,
            "fare_low": round(fare * LOW_FACTOR),
            "fare_high": round(fare * HIGH_FACTOR),
            "currency": "INR",
            "fare_status": "estimated",
            "availability_status": "unknown",
            "pickup_eta_minutes": None,
            "trip_duration_minutes": minutes,
            "distance_km": km,
            "fare_disclaimer": RATE_CARD_DISCLAIMER,
            "fare_estimate_note": f"{city_label} rate card ({period_label}).",
        })
    return rides


def provider_rate_card_estimate_rides(
    provider: str,
    metrics: dict[str, float],
    excluded_ride_types: set[str] | None = None,
    pickup: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Estimate a provider's remaining options from matching city rate cards."""
    excluded_ride_types = excluded_ride_types or set()
    city_key, city_label = detect_city(pickup)
    all_cards = city_rate_cards(city_key)
    options = [
        ride for ride in RIDE_OPTIONS
        if ride["provider"] == provider and ride["ride_type"] not in excluded_ride_types
    ]
    estimates = []
    for ride in options:
        rate_type = ride["ride_type"]
        cards = [card for card in all_cards if card[2] == rate_type]
        uses_auto_proxy = False
        if not cards and rate_type in {"sedan", "premium"}:
            cards = [card for card in all_cards if card[2] == "auto"]
            uses_auto_proxy = bool(cards)
        if not cards:
            continue

        km, minutes = metrics["distance_km"], metrics["duration_minutes"]
        provider_factor = PROVIDER_MULTIPLIERS.get(provider, 1.0)
        t_mult, period_label = time_factor(city_key, provider, rate_type)
        card_fares = [
            max(card[7], (
                card[3] + card[5] * max(km - card[4], 0) + card[6] * minutes
            ) * card[8] * provider_factor * t_mult)
            for card in cards
        ]
        fare = round(sum(card_fares) / len(card_fares))
        estimate_note = (
            f"{city_label} rate card ({period_label}); uses Rapido/Namma Yatri cards as a generic proxy, "
            f"not a quote from {provider}."
        )
        if uses_auto_proxy:
            estimate_note += " Sedan/Premium uses Auto rates as an approved proxy."
        estimates.append({
            "id": f"{ride['id']}-estimate",
            "provider": provider,
            "product_name": ride["product_name"],
            "ride_type": ride["ride_type"],
            "fare": fare,
            "fare_low": round(min(card_fares) * LOW_FACTOR),
            "fare_high": round(max(card_fares) * HIGH_FACTOR),
            "currency": "INR",
            "fare_status": "estimated",
            "availability_status": "unknown",
            "pickup_eta_minutes": None,
            "trip_duration_minutes": minutes,
            "distance_km": km,
            "fare_disclaimer": RATE_CARD_DISCLAIMER,
            "fare_estimate_note": estimate_note,
        })
    return estimates


def estimate_rides(
    metrics: dict[str, float],
    pickup: dict[str, Any] | None = None,
    drop: dict[str, Any] | None = None,
    model_path: Path = MODEL_PATH,
) -> list[dict[str, Any]]:
    """Resolve route estimates in order: trained model, then city provider rate cards."""
    model_rides = model_estimate_rides(metrics, pickup, drop, model_path)
    rate_rides = rate_card_estimate_rides(metrics, pickup=pickup)
    model_keys = {(ride["provider"], ride["ride_type"]) for ride in model_rides}
    return model_rides + [
        ride for ride in rate_rides
        if (ride["provider"], ride["ride_type"]) not in model_keys
    ]
