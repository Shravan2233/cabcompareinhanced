import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cabcompare.backend.models.schema import current_time_of_day
from cabcompare.backend.providers.options import RIDE_OPTIONS
from cabcompare.backend.services.estimates import estimate_rides, load_fare_model
from cabcompare.backend.services.fares import (
    ProviderRequestError,
    comparison_rides,
    ola_fares,
    uber_fares,
)


PICKUP = {"lat": 12.9716, "lng": 77.5946}
DROP = {"lat": 12.9352, "lng": 77.6245}
UBER_ENV = {
    "UBER_SERVER_TOKEN": "uber-test-secret",
    "UBER_COMPARISON_APPROVED": "true",
}
OLA_ENV = {"OLA_APP_TOKEN": "ola-test-secret"}


class ConstantFareModel:
    def predict(self, features):
        return [125.0] * len(features)


class ProviderFareTests(unittest.TestCase):
    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_uber_sends_route_and_secret_header_and_parses_price_ranges(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({
            "prices": [{
                "display_name": "uberX",
                "product_id": "uberx-1",
                "low_estimate": 120,
                "high_estimate": 160,
                "currency_code": "INR",
                "estimate": "₹120-160",
                "surge_multiplier": 1.5,
            }]
        }).encode())

        rides = uber_fares(PICKUP, DROP, UBER_ENV)

        self.assertEqual(len(rides), 1)
        ride = rides[0]
        self.assertEqual((ride["fare_low"], ride["fare_high"]), (120, 160))
        self.assertEqual(ride["currency"], "INR")
        self.assertEqual(ride["fare_status"], "live")
        self.assertIn("surge multiplier of 1.5", ride["fare_disclaimer"])
        request = urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(urlparse(request.full_url).netloc, "api.uber.com")
        self.assertEqual(urlparse(request.full_url).path, "/v1.2/estimates/price")
        self.assertEqual(query["start_latitude"], ["12.9716"])
        self.assertEqual(query["start_longitude"], ["77.5946"])
        self.assertEqual(query["end_latitude"], ["12.9352"])
        self.assertEqual(query["end_longitude"], ["77.6245"])
        self.assertEqual(request.get_header("Authorization"), "Token uber-test-secret")
        self.assertNotIn("uber-test-secret", repr(rides))

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_uber_missing_token_does_not_make_request(self, urlopen):
        rides = uber_fares(PICKUP, DROP, {"UBER_COMPARISON_APPROVED": "true"})
        urlopen.assert_not_called()
        self.assertTrue(all(ride["fare"] is None for ride in rides))
        self.assertIn("UBER_SERVER_TOKEN", rides[0]["fare_unavailable_reason"])

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_uber_requires_written_comparison_approval_even_with_token(self, urlopen):
        rides = uber_fares(PICKUP, DROP, {"UBER_SERVER_TOKEN": "token"})
        urlopen.assert_not_called()
        self.assertIn("Written Uber approval", rides[0]["fare_unavailable_reason"])

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_uber_auth_rate_limit_and_http_errors_are_unavailable(self, urlopen):
        for status, expected in (
            (401, "rejected"),
            (403, "rejected"),
            (429, "rate limit"),
            (503, "HTTP 503"),
        ):
            with self.subTest(status=status):
                urlopen.side_effect = urllib.error.HTTPError(
                    "https://api.uber.com/v1.2/estimates/price", status, "error", {}, None,
                )
                rides = uber_fares(PICKUP, DROP, UBER_ENV)
                self.assertTrue(all(ride["fare"] is None for ride in rides))
                self.assertIn(expected, rides[0]["fare_unavailable_reason"])

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_ola_sends_route_token_and_parses_product_fares(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({
            "products": [
                {"name": "Auto", "fare_min": 85, "fare_max": 110, "currency": "INR"},
                {"display_name": "Prime Sedan", "fare": 210, "currency_code": "INR"},
            ]
        }).encode())

        rides = ola_fares(PICKUP, DROP, OLA_ENV)

        self.assertEqual(len(rides), 2)
        auto = next(ride for ride in rides if ride["ride_type"] == "auto")
        sedan = next(ride for ride in rides if ride["ride_type"] == "sedan")
        self.assertEqual((auto["fare_low"], auto["fare_high"]), (85, 110))
        self.assertEqual((sedan["fare_low"], sedan["fare_high"]), (210, 210))
        self.assertTrue(all(ride["fare_status"] == "live" and ride["currency"] == "INR" for ride in rides))
        request = urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(urlparse(request.full_url).netloc, "devapi.olacabs.com")
        self.assertEqual(urlparse(request.full_url).path, "/v1/products")
        self.assertEqual(query["pickup_lat"], ["12.9716"])
        self.assertEqual(query["pickup_lng"], ["77.5946"])
        self.assertEqual(query["drop_lat"], ["12.9352"])
        self.assertEqual(query["drop_lng"], ["77.6245"])
        self.assertEqual(query["service_type"], ["p2p"])
        self.assertEqual(request.get_header("X-app-token"), "ola-test-secret")
        self.assertNotIn("ola-test-secret", repr(rides))

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_ola_missing_token_does_not_make_request(self, urlopen):
        rides = ola_fares(PICKUP, DROP, {})
        urlopen.assert_not_called()
        self.assertTrue(all(ride["fare"] is None for ride in rides))
        self.assertIn("OLA_APP_TOKEN", rides[0]["fare_unavailable_reason"])

    @patch("cabcompare.backend.services.fares._get_json")
    def test_ola_does_not_display_a_product_without_a_valid_currency(self, get_json):
        get_json.return_value = {"products": [{"name": "Auto", "fare_min": 85, "fare_max": 110}]}
        rides = ola_fares(PICKUP, DROP, OLA_ENV)
        self.assertTrue(all(ride["fare"] is None and ride["currency"] is None for ride in rides))
        self.assertIn("no priced products", rides[0]["fare_unavailable_reason"])

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_ola_auth_rate_limit_and_http_errors_are_unavailable(self, urlopen):
        for status, expected in (
            (401, "rejected"),
            (403, "rejected"),
            (429, "rate limit"),
            (503, "HTTP 503"),
        ):
            with self.subTest(status=status):
                urlopen.side_effect = urllib.error.HTTPError(
                    "https://devapi.olacabs.com/v1/products", status, "error", {}, None,
                )
                rides = ola_fares(PICKUP, DROP, OLA_ENV)
                self.assertTrue(all(ride["fare"] is None for ride in rides))
                self.assertIn(expected, rides[0]["fare_unavailable_reason"])

    @patch("cabcompare.backend.services.fares.urllib.request.urlopen")
    def test_provider_network_and_invalid_response_errors_are_unavailable(self, urlopen):
        for error, expected in (
            (urllib.error.URLError("offline"), "temporarily unreachable"),
            (io.BytesIO(b"not json"), "invalid fare response"),
        ):
            with self.subTest(expected=expected):
                if isinstance(error, io.BytesIO):
                    urlopen.side_effect = None
                    urlopen.return_value = error
                else:
                    urlopen.side_effect = error
                uber = uber_fares(PICKUP, DROP, UBER_ENV)
                if isinstance(error, io.BytesIO):
                    urlopen.return_value = io.BytesIO(b"not json")
                ola = ola_fares(PICKUP, DROP, OLA_ENV)
                self.assertIn(expected, uber[0]["fare_unavailable_reason"])
                self.assertIn(expected, ola[0]["fare_unavailable_reason"])

    def test_rapido_and_namma_yatri_receive_route_based_estimate_ranges(self):
        metrics = {"distance_km": 8, "duration_minutes": 30}
        with patch("cabcompare.backend.services.estimates.load_fare_model", return_value=None):
            rides = estimate_rides(metrics)
        self.assertEqual({ride["provider"] for ride in rides}, {"Rapido", "Namma Yatri"})
        self.assertEqual({ride["currency"] for ride in rides}, {"INR"})
        self.assertTrue(all(ride["fare_status"] == "estimated" for ride in rides))
        self.assertTrue(all(ride["fare_low"] < ride["fare"] < ride["fare_high"] for ride in rides))
        self.assertTrue(all("surge" in ride["fare_disclaimer"] for ride in rides))
        by_provider = {ride["provider"]: ride for ride in rides if ride["ride_type"] == "auto"}
        self.assertEqual(by_provider["Rapido"]["distance_km"], 8)
        self.assertEqual(by_provider["Namma Yatri"]["trip_duration_minutes"], 30)

    def test_missing_uber_and_ola_tokens_fall_back_to_estimated_fares(self):
        metrics = {"distance_km": 8, "duration_minutes": 30}
        for env in ({}, {"UBER_SERVER_TOKEN": "", "OLA_APP_TOKEN": ""}):
            with self.subTest(env=env), patch(
                "cabcompare.backend.services.estimates.load_fare_model",
                return_value=None,
            ):
                rides = comparison_rides(PICKUP, DROP, metrics, env)
            estimates = [ride for ride in rides if ride["provider"] in {"Uber", "Ola"}]
            self.assertEqual(
                {(ride["provider"], ride["ride_type"], ride["fare_status"]) for ride in estimates},
                {
                    ("Uber", "bike", "estimated"),
                    ("Uber", "auto", "estimated"),
                    ("Uber", "sedan", "estimated"),
                    ("Uber", "premium", "estimated"),
                    ("Ola", "bike", "estimated"),
                    ("Ola", "auto", "estimated"),
                    ("Ola", "sedan", "estimated"),
                    ("Ola", "premium", "estimated"),
                },
            )
            self.assertTrue(all(ride["currency"] == "INR" for ride in estimates))
            self.assertTrue(all(ride["fare_low"] < ride["fare"] < ride["fare_high"] for ride in estimates))
            self.assertTrue(all(
                ride["fare_disclaimer"] ==
                "Rate-card estimate from route distance and duration; actual fares may vary with demand, "
                "surge, traffic, tolls, and provider pricing. Confirm in the app."
                for ride in estimates
            ))
            self.assertTrue(all("generic proxy" in ride["fare_estimate_note"] for ride in estimates))
            sedan_fare = next(r["fare"] for r in estimates if r["provider"] == "Uber" and r["ride_type"] == "sedan")
            auto_fare = next(r["fare"] for r in estimates if r["provider"] == "Uber" and r["ride_type"] == "auto")
            self.assertGreater(sedan_fare, auto_fare)

    def test_trained_model_predictions_precede_rate_cards(self):
        categories = {
            "provider": sorted({ride["provider"].casefold() for ride in RIDE_OPTIONS}),
            "vehicle": sorted({ride["product_name"].casefold() for ride in RIDE_OPTIONS}),
            "time_of_day": [current_time_of_day()],
            "currency": ["INR"],
        }
        artifact = {
            "format_version": 1,
            "feature_columns": [
                "provider", "vehicle", "time_of_day", "currency", "distance_km",
                "duration_minutes", "pickup_lat", "pickup_lng", "destination_lat", "destination_lng",
            ],
            "currency": "INR",
            "feature_categories": categories,
            "model": ConstantFareModel(),
        }
        with patch("cabcompare.backend.services.estimates.load_fare_model", return_value=artifact):
            rides = estimate_rides(
                {"distance_km": 8, "duration_minutes": 30},
                PICKUP,
                DROP,
            )
        self.assertEqual(len(rides), len(RIDE_OPTIONS))
        self.assertTrue(all(ride["fare_status"] == "model" and ride["fare"] == 125 for ride in rides))
        self.assertTrue(all("not a provider quote" in ride["fare_disclaimer"] for ride in rides))

    def test_invalid_model_prediction_falls_back_to_rate_cards(self):
        class InvalidModel:
            def predict(self, features):
                raise ValueError("unusable model")

        artifact = {
            "format_version": 1,
            "feature_columns": [
                "provider", "vehicle", "time_of_day", "currency", "distance_km",
                "duration_minutes", "pickup_lat", "pickup_lng", "destination_lat", "destination_lng",
            ],
            "currency": "INR",
            "feature_categories": {
                "provider": sorted({ride["provider"].casefold() for ride in RIDE_OPTIONS}),
                "vehicle": sorted({ride["product_name"].casefold() for ride in RIDE_OPTIONS}),
                "time_of_day": [current_time_of_day()],
                "currency": ["INR"],
            },
            "model": InvalidModel(),
        }
        with patch("cabcompare.backend.services.estimates.load_fare_model", return_value=artifact):
            rides = estimate_rides(
                {"distance_km": 8, "duration_minutes": 30},
                PICKUP,
                DROP,
            )
        self.assertEqual({ride["fare_status"] for ride in rides}, {"estimated"})
        self.assertEqual({ride["provider"] for ride in rides}, {"Rapido", "Namma Yatri"})

    def test_live_provider_quote_takes_precedence_and_rate_cards_fill_missing_options(self):
        live_uber = {
            "id": "uber-live", "provider": "Uber", "ride_type": "auto",
            "fare": 90, "currency": "INR", "fare_status": "live",
        }
        unavailable_ola = {
            "id": "ola-unavailable", "provider": "Ola", "ride_type": "auto",
            "fare": None, "currency": None, "fare_status": "unavailable",
        }
        model_rides = [
            {"id": "uber-auto-model", "provider": "Uber", "ride_type": "auto", "fare": 125,
             "currency": "INR", "fare_status": "model"},
            {"id": "uber-sedan-model", "provider": "Uber", "ride_type": "sedan", "fare": 130,
             "currency": "INR", "fare_status": "model"},
            {"id": "ola-auto-model", "provider": "Ola", "ride_type": "auto", "fare": 125,
             "currency": "INR", "fare_status": "model"},
            {"id": "rapido-bike-model", "provider": "Rapido", "ride_type": "bike", "fare": 125,
             "currency": "INR", "fare_status": "model"},
        ]
        with (
            patch("cabcompare.backend.services.fares.uber_fares", return_value=[live_uber]),
            patch("cabcompare.backend.services.fares.ola_fares", return_value=[unavailable_ola]),
            patch("cabcompare.backend.services.fares.estimate_rides", return_value=model_rides),
        ):
            rides = comparison_rides(PICKUP, DROP, {"distance_km": 5, "duration_minutes": 20}, {})
        self.assertEqual(
            {(ride["provider"], ride["fare_status"]) for ride in rides},
            {("Uber", "live"), ("Uber", "estimated"), ("Ola", "estimated"), ("Rapido", "model")},
        )
        self.assertIn("uber-sedan-estimate", {ride["id"] for ride in rides})

    def test_training_schema_is_header_only_and_rejects_empty_data(self):
        from cabcompare.backend.models.train_fare_model import _read_dataset

        schema_path = Path(__file__).parents[1] / "models" / "fare_training_schema.csv"
        with self.assertRaisesRegex(ValueError, "at least 5 labeled fare rows"):
            _read_dataset(schema_path)

    def test_model_loader_reads_a_compatible_local_artifact(self):
        import joblib

        artifact = {
            "format_version": 1,
            "feature_columns": [
                "provider", "vehicle", "time_of_day", "currency", "distance_km",
                "duration_minutes", "pickup_lat", "pickup_lng", "destination_lat", "destination_lng",
            ],
            "currency": "INR",
            "feature_categories": {},
            "model": ConstantFareModel(),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fare_model.joblib"
            joblib.dump(artifact, path)
            loaded = load_fare_model(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["currency"], "INR")

    def test_model_loader_treats_a_missing_artifact_as_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.joblib"
            self.assertIsNone(load_fare_model(path))

    @patch("cabcompare.backend.services.fares._get_json")
    def test_hybrid_results_use_rate_card_estimates_after_api_failures(self, get_json):
        get_json.side_effect = ProviderRequestError(status_code=429)
        with patch("cabcompare.backend.services.estimates.load_fare_model", return_value=None):
            rides = comparison_rides(
                PICKUP,
                DROP,
                {"distance_km": 5, "duration_minutes": 20},
                {**UBER_ENV, **OLA_ENV},
            )
        self.assertTrue(all(ride["fare_status"] == "estimated" for ride in rides))

    def test_city_rate_cards_differ_between_delhi_and_bengaluru(self):
        metrics = {"distance_km": 10, "duration_minutes": 25}
        blr = estimate_rides(metrics, pickup={"lat": 12.9784, "lng": 77.6408})
        del_rides = estimate_rides(metrics, pickup={"lat": 28.6315, "lng": 77.2167})
        blr_auto = next(r for r in blr if r["provider"] == "Namma Yatri" and r["ride_type"] == "auto")
        del_auto = next(r for r in del_rides if r["provider"] == "Namma Yatri" and r["ride_type"] == "auto")
        self.assertGreater(blr_auto["fare"], del_auto["fare"])
        self.assertIn("Bengaluru", blr_auto["fare_estimate_note"])
        self.assertIn("Delhi NCR", del_auto["fare_estimate_note"])

    def test_missing_route_metrics_make_estimated_provider_fares_unavailable(self):
        rides = comparison_rides(PICKUP, DROP, None, {})
        estimates = [ride for ride in rides if ride["provider"] in {"Rapido", "Namma Yatri"}]
        self.assertTrue(all(ride["fare"] is None for ride in estimates))
        self.assertTrue(all("Route distance" in ride["fare_unavailable_reason"] for ride in estimates))


if __name__ == "__main__":
    unittest.main()
