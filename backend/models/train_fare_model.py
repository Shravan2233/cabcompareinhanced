from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .schema import (
    CATEGORICAL_FEATURES,
    CSV_COLUMNS,
    FEATURE_COLUMNS,
    NUMERICAL_FEATURES,
    TARGET_COLUMN,
)

MODEL_ARTIFACT_PATH = Path(__file__).with_name("fare_model.joblib")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_TIME_BUCKETS = {"morning", "afternoon", "evening", "night"}
_COORDINATE_BOUNDS = {
    "pickup_lat": (-90, 90),
    "destination_lat": (-90, 90),
    "pickup_lng": (-180, 180),
    "destination_lng": (-180, 180),
}


def _pipeline() -> Pipeline:
    preprocess = ColumnTransformer(
        transformers=[
            (
                "categories",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("one_hot", OneHotEncoder(handle_unknown="ignore")),
                ]),
                list(CATEGORICAL_FEATURES),
            ),
            (
                "numbers",
                Pipeline([("imputer", SimpleImputer(strategy="median"))]),
                list(NUMERICAL_FEATURES),
            ),
        ],
        remainder="drop",
    )
    return Pipeline([
        ("preprocess", preprocess),
        ("regressor", RandomForestRegressor(
            n_estimators=300,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )),
    ])


def _read_dataset(dataset_path: Path) -> pd.DataFrame:
    data = pd.read_csv(dataset_path)
    missing_columns = sorted(set(CSV_COLUMNS) - set(data.columns))
    if missing_columns:
        raise ValueError(f"Dataset is missing required columns: {', '.join(missing_columns)}.")
    if len(data) < 5:
        raise ValueError("Provide at least 5 labeled fare rows to train and evaluate the model.")

    data = data.loc[:, CSV_COLUMNS].copy()
    for column in CATEGORICAL_FEATURES:
        data[column] = data[column].astype("string").str.strip()
        if data[column].isna().any() or (data[column] == "").any():
            raise ValueError(f"Column '{column}' must be filled for every row.")

    data["provider"] = data["provider"].str.casefold()
    data["vehicle"] = data["vehicle"].str.casefold()
    data["time_of_day"] = data["time_of_day"].str.casefold()
    if not data["time_of_day"].isin(_TIME_BUCKETS).all():
        raise ValueError("time_of_day must be morning, afternoon, evening, or night (India time).")
    data["currency"] = data["currency"].str.upper()
    if not data["currency"].map(lambda value: bool(_CURRENCY_PATTERN.fullmatch(value))).all():
        raise ValueError("currency must be an ISO-style three-letter code such as INR.")
    currencies = data["currency"].unique()
    if len(currencies) != 1:
        raise ValueError("Train one model per currency; fare amounts in different currencies cannot be mixed.")

    numeric_columns = (*NUMERICAL_FEATURES, TARGET_COLUMN)
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    numeric_values = data.loc[:, numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all():
        raise ValueError("Distance, duration, coordinates, and fare must be finite numeric values.")
    if (data["distance_km"] <= 0).any() or (data["duration_minutes"] <= 0).any() or (data[TARGET_COLUMN] <= 0).any():
        raise ValueError("Distance, duration, and fare values must be greater than zero.")
    for column, (minimum, maximum) in _COORDINATE_BOUNDS.items():
        if not data[column].between(minimum, maximum).all():
            raise ValueError(f"Column '{column}' contains coordinates outside valid bounds.")
    return data


def train_model(dataset_path: Path, artifact_path: Path = MODEL_ARTIFACT_PATH) -> dict[str, Any]:
    data = _read_dataset(Path(dataset_path))
    features = data.loc[:, FEATURE_COLUMNS]
    target = data[TARGET_COLUMN]
    train_features, test_features, train_target, test_target = train_test_split(
        features,
        target,
        test_size=0.2,
        random_state=42,
    )

    evaluator = _pipeline()
    evaluator.fit(train_features, train_target)
    predictions = evaluator.predict(test_features)
    metrics = {
        "mae": float(mean_absolute_error(test_target, predictions)),
        "rmse": float(np.sqrt(mean_squared_error(test_target, predictions))),
    }

    model = _pipeline()
    model.fit(features, target)
    artifact = {
        "format_version": 1,
        "model": model,
        "currency": str(data["currency"].iloc[0]),
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_categories": {
            column: sorted(data[column].unique().tolist())
            for column in CATEGORICAL_FEATURES
        },
        "training_rows": len(data),
        "metrics": metrics,
    }
    artifact_path = Path(artifact_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a fare regression model from labeled provider fares.")
    parser.add_argument("dataset", type=Path, help="CSV file with the fare_training_schema.csv columns")
    parser.add_argument("--output", type=Path, default=MODEL_ARTIFACT_PATH, help="Model artifact output path")
    args = parser.parse_args()
    try:
        artifact = train_model(args.dataset, args.output)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        parser.error(str(error))
    print(f"Trained on {artifact['training_rows']} labeled rows ({artifact['currency']}).")
    print(f"Holdout MAE: {artifact['metrics']['mae']:.2f} {artifact['currency']}")
    print(f"Holdout RMSE: {artifact['metrics']['rmse']:.2f} {artifact['currency']}")
    print(f"Saved model: {args.output}")


if __name__ == "__main__":
    main()
