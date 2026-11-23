import unittest
from unittest.mock import patch
from urllib.parse import unquote

from cabcompare.backend.app import create_app
from cabcompare.backend.services.fares import clear_quote_cache


class ApiTests(unittest.TestCase):
    def setUp(self):
        clear_quote_cache()
        credentials = patch.dict("os.environ", {
            "UBER_OAUTH_TOKEN": "",
            "UBER_SERVER_TOKEN": "",
            "UBER_COMPARISON_APPROVED": "false",
            "OLA_APP_TOKEN": "",
            "OLA_BEARER_TOKEN": "",
            "RAPIDO_API_URL": "",
            "RAPIDO_AUTH_TOKEN": "",
            "NAMMA_YATRI_BAP_SEARCH_URL": "",
            "NAMMA_YATRI_AUTH_TOKEN": "",
            "RATE_LIMIT_COMPARE_PER_MIN": "30",
        })
        credentials.start()
        self.addCleanup(credentials.stop)
        patcher = patch("cabcompare.backend.app.osm_route_metrics", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = create_app().test_client()

    def test_health_reports_hybrid_fare_mode(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fare_mode"], "hybrid")

    def test_compare_requires_valid_route(self):
        response = self.client.post("/api/rides/compare", json={"pickup": "", "destination": "B"})
        self.assertEqual(response.status_code, 400)

    def test_unconfigured_route_with_metrics_returns_calibrated_city_estimates(self):
        response = self.client.post("/api/rides/compare", json={
            "pickup": "Indiranagar, Bengaluru",
            "destination": "MG Road, Bengaluru",
            "pickup_coords": {"lat": 12.9784, "lng": 77.6408},
            "destination_coords": {"lat": 12.9756, "lng": 77.6066},
            "route_metrics": {"distance_km": 5.6, "duration_minutes": 14},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fare_source"], "estimated")
        self.assertIsNotNone(response.json["cheapest_quote"])
        rides = response.json["rides"]
        self.assertEqual({r["provider"] for r in rides}, {"Uber", "Ola", "Rapido", "Namma Yatri"})
        self.assertTrue(all(r["quoteType"] == "FARE_ESTIMATE" for r in rides))
        self.assertTrue(all(r["quoteSource"] == "rate_card" for r in rides))
        self.assertTrue(all(r["currency"] == "INR" and r["fare_low"] <= r["fare"] <= r["fare_high"] for r in rides))
        self.assertTrue(any(r["is_lowest"] for r in rides))
        self.assertIn("rate-card estimates", response.json["notice"])

    def test_missing_route_metrics_fallback_stays_unavailable_honestly(self):
        response = self.client.post("/api/rides/compare", json={"pickup": "Unknown A", "destination": "Unknown B"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fare_source"], "unavailable")
        self.assertTrue(all(r["quoteType"] == "UNAVAILABLE" and r["fare"] is None for r in response.json["rides"]))

    def test_booking_links_report_truthful_prefill_status(self):
        response = self.client.post("/api/rides/compare", json={
            "pickup": "Indiranagar",
            "destination": "MG Road",
            "pickup_coords": {"lat": 12.9784, "lng": 77.6408},
            "destination_coords": {"lat": 12.9756, "lng": 77.6066},
        })
        self.assertEqual(response.status_code, 200)
        hosts = {"Uber": "m.uber.com", "Ola": "book.olacabs.com", "Rapido": "www.rapido.bike", "Namma Yatri": "nammayatri.in"}
        for ride in response.json["rides"]:
            self.assertTrue(ride["booking_url"].startswith("https://" + hosts[ride["provider"]]))
        uber = next(r for r in response.json["rides"] if r["provider"] == "Uber")
        self.assertIn("12.9756", unquote(uber["booking_url"]))
        self.assertIn("12.9784", unquote(uber["booking_url"]))
        self.assertTrue(uber["booking"]["prefills_route"])
        ola = next(r for r in response.json["rides"] if r["provider"] == "Ola")
        self.assertIn("12.975600", unquote(ola["booking_url"]))
        self.assertTrue(ola["booking"]["prefills_route"])
        rapido = next(r for r in response.json["rides"] if r["provider"] == "Rapido")
        self.assertFalse(rapido["booking"]["prefills_route"])
        self.assertEqual(rapido["booking"]["open_mode"], "home_screen")
        ny = next(r for r in response.json["rides"] if r["provider"] == "Namma Yatri")
        self.assertEqual(ny["booking"]["url"], "https://nammayatri.in/")
        self.assertFalse(ny["booking"]["prefills_route"])

    def test_invalid_coordinates_and_metrics_are_rejected(self):
        bad_coords = self.client.post("/api/rides/compare", json={
            "pickup": "A", "destination": "B", "pickup_coords": {"lat": 999, "lng": 0}})
        self.assertEqual(bad_coords.status_code, 400)
        for bad in ({"distance_km": -1, "duration_minutes": 5}, {"distance_km": 9999, "duration_minutes": 5}, {"x": 1}):
            resp = self.client.post("/api/rides/compare", json={"pickup": "A", "destination": "B", "route_metrics": bad})
            self.assertEqual(resp.status_code, 400)

    def test_provider_status_is_transparent(self):
        response = self.client.get("/api/providers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {provider["id"]: provider["status"] for provider in response.json["providers"]},
            {
                "uber": "hybrid",
                "rapido": "estimated",
                "ola": "hybrid",
                "namma-yatri": "estimated",
            },
        )

    def test_rate_limiter_enforces_429_when_limit_exceeded(self):
        with patch.dict("os.environ", {"RATE_LIMIT_COMPARE_PER_MIN": "2"}):
            limited_client = create_app().test_client()
            payload = {"pickup": "A", "destination": "B"}
            self.assertEqual(limited_client.post("/api/rides/compare", json=payload).status_code, 200)
            self.assertEqual(limited_client.post("/api/rides/compare", json=payload).status_code, 200)
            blocked = limited_client.post("/api/rides/compare", json=payload)
            self.assertEqual(blocked.status_code, 429)
            self.assertIn("Retry-After", blocked.headers)

    def test_cors_accepts_only_configured_or_local_origins(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:5174"):
            response = self.client.get("/api/health", headers={"Origin": origin})
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
        blocked = self.client.get("/api/health", headers={"Origin": "https://untrusted.example"})
        self.assertIsNone(blocked.headers.get("Access-Control-Allow-Origin"))


class FreeRoutingTests(unittest.TestCase):
    def test_osm_lookup_populates_route_metrics_and_estimated_fares(self):
        found = {
            "metrics": {"distance_km": 9.4, "duration_minutes": 31},
            "pickup": {"lat": 12.9, "lng": 77.6},
            "destination": {"lat": 12.96, "lng": 77.7},
            "geometry": [[77.6, 12.9], [77.7, 12.96]],
        }
        with patch("cabcompare.backend.app.osm_route_metrics", return_value=found):
            client = create_app().test_client()
            response = client.post("/api/rides/compare", json={"pickup": "A", "destination": "B"})
        self.assertEqual(response.json["fare_source"], "estimated")
        self.assertEqual(response.json["route_metrics"]["distance_km"], 9.4)
        self.assertEqual(response.json["route_geometry"], [[77.6, 12.9], [77.7, 12.96]])
        uber = next(r for r in response.json["rides"] if r["provider"] == "Uber")
        self.assertIn("12.96", unquote(uber["booking_url"]))

    def test_place_suggest_and_reverse_endpoints(self):
        sample = [{"id": "hub-0", "main": "Indiranagar", "secondary": "Bengaluru, Karnataka",
                   "text": "Indiranagar, Bengaluru, Karnataka", "lat": 12.9784, "lng": 77.6408}]
        with (
            patch("cabcompare.backend.app.suggest_places", return_value=sample),
            patch("cabcompare.backend.app.reverse_geocode", return_value="100 Feet Road, Bengaluru"),
        ):
            client = create_app().test_client()
            s_resp = client.get("/api/places/suggest?q=Indira")
            r_resp = client.get("/api/places/reverse?lat=12.9784&lng=77.6408")
        self.assertEqual(s_resp.status_code, 200)
        self.assertEqual(s_resp.json["suggestions"], sample)
        self.assertEqual(r_resp.status_code, 200)
        self.assertEqual(r_resp.json["text"], "100 Feet Road, Bengaluru")


if __name__ == "__main__":
    unittest.main()
