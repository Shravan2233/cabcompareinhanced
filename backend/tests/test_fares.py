import io
import json
import unittest
import urllib.error
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cabcompare.backend.providers import namma_yatri, ola, rapido, uber
from cabcompare.backend.providers.base import ProviderRequestError, request_json
from cabcompare.backend.providers.options import RIDE_OPTIONS
from cabcompare.backend.providers.rates import IST, detect_city, estimate_option_fare, time_factor_and_label
from cabcompare.backend.services.fares import clear_quote_cache, comparison_rides, ola_fares, uber_fares


BENGALURU_PICKUP = {"lat": 12.9784, "lng": 77.6408}  # Indiranagar
BENGALURU_DROP = {"lat": 12.9756, "lng": 77.6066}    # MG Road
DELHI_PICKUP = {"lat": 28.6315, "lng": 77.2167}

UBER_ENV = {
    "UBER_SERVER_TOKEN": "uber-test-secret",
    "UBER_COMPARISON_APPROVED": "true",
}
OLA_ENV = {"OLA_APP_TOKEN": "ola-test-secret"}
RAPIDO_ENV = {
    "RAPIDO_API_URL": "https://partner-gateway.example/rapido/quotes",
    "RAPIDO_AUTH_TOKEN": "rapido-test-secret",
    "RAPIDO_DEVICE_ID": "device-123",
}
NY_ENV = {
    "NAMMA_YATRI_BAP_SEARCH_URL": "https://ondc-bap.example/mobility/search",
    "NAMMA_YATRI_AUTH_TOKEN": "ny-test-secret",
}


class ProviderIntegrationTests(unittest.TestCase):
    def setUp(self):
        clear_quote_cache()

    @patch("cabcompare.backend.providers.base.urllib.request.urlopen")
    def test_uber_parses_range_as_fare_estimate_and_keeps_token_secret(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({
            "prices": [{
                "display_name": "UberGo",
                "product_id": "ubergo-1",
                "low_estimate": 120,
                "high_estimate": 160,
                "currency_code": "INR",
                "estimate": "₹120-160",
                "pickup_estimate": 180,
                "duration": 900,
                "surge_multiplier": 1.5,
            }]
        }).encode())

        rides = uber_fares(BENGALURU_PICKUP, BENGALURU_DROP, UBER_ENV)

        self.assertEqual(len(rides), 1)
        ride = rides[0]
        self.assertEqual(ride["quoteType"], "FARE_ESTIMATE")
        self.assertEqual(ride["status"], "success")
        self.assertEqual(ride["fareRange"], {"min": 120.0, "max": 160.0})
        self.assertEqual(ride["etaMinutes"], 3)
        self.assertEqual(ride["currency"], "INR")
        self.assertEqual(ride["availability_status"], "available")
        self.assertTrue(ride["retrievedAt"])
        self.assertIn("1.5x surge", ride["fare_disclaimer"])
        request = urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["start_latitude"], ["12.9784"])
        self.assertEqual(query["end_latitude"], ["12.9756"])
        self.assertEqual(request.get_header("Authorization"), "Token uber-test-secret")
        self.assertNotIn("uber-test-secret", repr(rides))

    @patch("cabcompare.backend.providers.base.urllib.request.urlopen")
    def test_uber_rejects_unapproved_comparison_or_missing_token(self, urlopen):
        no_token = uber.fetch_quotes(BENGALURU_PICKUP, BENGALURU_DROP, {"UBER_COMPARISON_APPROVED": "true"})
        no_approval = uber.fetch_quotes(BENGALURU_PICKUP, BENGALURU_DROP, {"UBER_SERVER_TOKEN": "token"})
        urlopen.assert_not_called()
        self.assertTrue(all(r["quoteType"] == "UNAVAILABLE" and r["fare"] is None for r in no_token))
        self.assertTrue(all(r["quoteType"] == "UNAVAILABLE" and r["fare"] is None for r in no_approval))
        self.assertIn("not configured", no_token[0]["error"])
        self.assertIn("Written Uber approval", no_approval[0]["error"])

    @patch("cabcompare.backend.providers.base.urllib.request.urlopen")
    def test_ola_distinguishes_live_quote_from_estimate_range(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps({
            "products": [
                {"name": "Ola Auto", "fare_min": 85, "fare_max": 110, "currency": "INR", "eta_minutes": 4},
                {"display_name": "Prime Sedan", "fare": 210, "currency_code": "INR", "eta_minutes": 5},
            ]
        }).encode())

        rides = ola_fares(BENGALURU_PICKUP, BENGALURU_DROP, OLA_ENV)

        auto = next(r for r in rides if r["ride_type"] == "auto")
        sedan = next(r for r in rides if r["ride_type"] == "sedan")
        self.assertEqual(auto["quoteType"], "FARE_ESTIMATE")
        self.assertEqual(auto["fareRange"], {"min": 85.0, "max": 110.0})
        self.assertEqual(sedan["quoteType"], "LIVE_QUOTE")
        self.assertEqual(sedan["fare"], 210.0)
        self.assertEqual(sedan["etaMinutes"], 5)
        self.assertNotIn("ola-test-secret", repr(rides))

    @patch("cabcompare.backend.providers.base.urllib.request.urlopen")
    def test_rapido_and_namma_yatri_use_authorized_gateways_when_configured(self, urlopen):
        rapido_payload = json.dumps({
            "quotes": [{"serviceName": "Bike Direct", "totalFare": 56, "currency": "INR", "eta": 3}]
        }).encode()
        ny_payload = json.dumps({
            "estimates": [{"vehicleVariant": "Auto", "estimatedFare": 143, "currency": "INR", "estimatedPickupDuration": 120}]
        }).encode()
        urlopen.side_effect = [io.BytesIO(rapido_payload), io.BytesIO(ny_payload)]

        rap_rides = rapido.fetch_quotes(BENGALURU_PICKUP, BENGALURU_DROP, RAPIDO_ENV)
        ny_rides = namma_yatri.fetch_quotes(BENGALURU_PICKUP, BENGALURU_DROP, NY_ENV)

        self.assertEqual(rap_rides[0]["quoteType"], "LIVE_QUOTE")
        self.assertEqual(rap_rides[0]["fare"], 56.0)
        self.assertEqual(ny_rides[0]["quoteType"], "LIVE_QUOTE")
        self.assertEqual(ny_rides[0]["fare"], 143.0)
        self.assertEqual(ny_rides[0]["etaMinutes"], 2)
        self.assertNotIn("rapido-test-secret", repr(rap_rides))
        self.assertNotIn("ny-test-secret", repr(ny_rides))

    def test_unconfigured_providers_with_metrics_return_calibrated_city_estimates(self):
        rides = comparison_rides(BENGALURU_PICKUP, BENGALURU_DROP, {"distance_km": 5.6, "duration_minutes": 14}, {})
        self.assertEqual(len(rides), len(RIDE_OPTIONS))
        self.assertEqual({r["provider"] for r in rides}, {"Uber", "Ola", "Rapido", "Namma Yatri"})
        self.assertTrue(all(r["quoteType"] == "FARE_ESTIMATE" and r["quoteSource"] == "rate_card" for r in rides))
        self.assertTrue(all(r["currency"] == "INR" and r["fare_low"] < r["fare"] < r["fare_high"] for r in rides))
        self.assertTrue(all("Bengaluru" in r["fare_disclaimer"] for r in rides))

    def test_live_quote_takes_priority_and_backfills_missing_options_with_rate_card(self):
        live_ola = [{
            "id": "ola-live-auto", "provider": "Ola", "vehicleType": "Ola Auto", "product_name": "Ola Auto",
            "ride_type": "auto", "fare": 115.0, "fareRange": {"min": 115.0, "max": 115.0},
            "fare_low": 115.0, "fare_high": 115.0, "currency": "INR",
            "quoteType": "LIVE_QUOTE", "fare_status": "live", "availability_status": "available", "status": "success",
        }]
        with patch("cabcompare.backend.services.fares.ola_fares", return_value=live_ola):
            rides = comparison_rides(BENGALURU_PICKUP, BENGALURU_DROP, {"distance_km": 5.6, "duration_minutes": 14}, {})
        ola_auto = [r for r in rides if r["provider"] == "Ola" and r["ride_type"] == "auto"]
        ola_sedan = [r for r in rides if r["provider"] == "Ola" and r["ride_type"] == "sedan"]
        self.assertEqual(ola_auto[0]["quoteType"], "LIVE_QUOTE")
        self.assertEqual(ola_auto[0]["fare"], 115.0)
        self.assertEqual(ola_sedan[0]["quoteSource"], "rate_card")

    def test_city_tariffs_and_ist_time_factors_calibrate_bengaluru_vs_delhi(self):
        metrics = {"distance_km": 5.6, "duration_minutes": 14}
        day_ist = datetime(2026, 11, 23, 14, 0, tzinfo=IST)
        night_ist = datetime(2026, 11, 23, 23, 30, tzinfo=IST)
        self.assertEqual(detect_city(BENGALURU_PICKUP), ("bengaluru", "Bengaluru"))
        self.assertEqual(detect_city(DELHI_PICKUP), ("delhi", "Delhi NCR"))
        self.assertEqual(time_factor_and_label(day_ist)[0], 1.00)
        self.assertEqual(time_factor_and_label(night_ist)[0], 1.25)

        ny_auto = next(r for r in RIDE_OPTIONS if r["id"] == "namma-yatri-auto")
        blr_day = estimate_option_fare(ny_auto, metrics, BENGALURU_PICKUP, now=day_ist)
        blr_night = estimate_option_fare(ny_auto, metrics, BENGALURU_PICKUP, now=night_ist)
        del_day = estimate_option_fare(ny_auto, metrics, DELHI_PICKUP, now=day_ist)
        self.assertGreater(blr_day["fare"], del_day["fare"])
        self.assertGreater(blr_night["fare"], blr_day["fare"])
        self.assertTrue(70 <= blr_day["fare"] <= 140)

    @patch("cabcompare.backend.providers.base.urllib.request.urlopen")
    def test_provider_errors_and_expired_auth_return_unavailable_on_direct_fetch(self, urlopen):
        for status, snippet in (
            (401, "expired"),
            (403, "expired"),
            (429, "rate limit"),
            (503, "HTTP 503"),
        ):
            with self.subTest(status=status):
                urlopen.side_effect = urllib.error.HTTPError(
                    "https://api.uber.com/v1.2/estimates/price", status, "err", {}, None
                )
                rides = uber.fetch_quotes(BENGALURU_PICKUP, BENGALURU_DROP, UBER_ENV)
                self.assertTrue(all(r["quoteType"] == "UNAVAILABLE" and r["fare"] is None for r in rides))
                self.assertIn(snippet, rides[0]["error"])

        urlopen.side_effect = None
        urlopen.return_value = io.BytesIO(b"invalid json")
        invalid_ola = ola.fetch_quotes(BENGALURU_PICKUP, BENGALURU_DROP, OLA_ENV)
        self.assertEqual(invalid_ola[0]["quoteType"], "UNAVAILABLE")
        self.assertIn("invalid fare response", invalid_ola[0]["error"])

    def test_rejects_insecure_http_remote_base_urls(self):
        rides = ola.fetch_quotes(
            BENGALURU_PICKUP,
            BENGALURU_DROP,
            {**OLA_ENV, "OLA_API_BASE_URL": "http://insecure.example.com"},
        )
        self.assertEqual(rides[0]["quoteType"], "UNAVAILABLE")
        self.assertIn("HTTPS", rides[0]["error"])

    def test_request_timeout_maps_to_provider_request_error(self):
        with patch("cabcompare.backend.providers.base.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(ProviderRequestError) as ctx:
                request_json("https://api.uber.com/v1.2/estimates/price", {})
        self.assertIsNone(ctx.exception.status_code)

    def test_quote_ttl_cache_avoids_duplicate_upstream_calls_for_same_route(self):
        call_count = 0

        def fake_urlopen(req, timeout=5):
            nonlocal call_count
            call_count += 1
            return io.BytesIO(json.dumps({
                "products": [{"name": "Auto", "fare": 95, "currency": "INR"}]
            }).encode())

        with (
            patch.dict("os.environ", {"OLA_APP_TOKEN": "ola-secret", "UBER_SERVER_TOKEN": "", "RAPIDO_API_URL": "", "NAMMA_YATRI_BAP_SEARCH_URL": ""}),
            patch("cabcompare.backend.providers.base.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            first = comparison_rides(BENGALURU_PICKUP, BENGALURU_DROP, None)
            second = comparison_rides(BENGALURU_PICKUP, BENGALURU_DROP, None)
        self.assertEqual(call_count, 1)
        self.assertEqual(first[0]["quoteType"], second[0]["quoteType"])


if __name__ == "__main__":
    unittest.main()
