from __future__ import annotations

from datetime import datetime, timedelta, timezone

CATEGORICAL_FEATURES = ("provider", "vehicle", "time_of_day", "currency")
NUMERICAL_FEATURES = (
    "distance_km",
    "duration_minutes",
    "pickup_lat",
    "pickup_lng",
    "destination_lat",
    "destination_lng",
)
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERICAL_FEATURES
TARGET_COLUMN = "fare"
CSV_COLUMNS = FEATURE_COLUMNS + (TARGET_COLUMN,)


def current_time_of_day() -> str:
    """Return a training-schema bucket using India Standard Time."""
    india_offset = timezone(timedelta(hours=5, minutes=30))
    hour = datetime.now(timezone.utc).astimezone(india_offset).hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"
