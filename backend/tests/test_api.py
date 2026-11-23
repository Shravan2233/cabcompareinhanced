import unittest
from urllib.parse import unquote
from unittest.mock import patch

from cabcompare.backend.app import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        credentials = patch.dict("os.environ", {
            "UBER_SERVER_TOKEN": "",
            "UBER_COMPARISON_APPROVED": "false",
            "OLA_APP_TOKEN": "",
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

    def test_compare_does_not_return_sample_or_estimated_fares(self):
        response = self.client.post("/api/rides/compare", json={"pickup": "A", "destination": "B"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fare_source"], "unavailable")
        self.assertTrue(all(ride["fare_status"] == "unavailable" for ride in response.json["rides"]))
        self.assertTrue(all(ride["fare"] is None and ride["currency"] is None for ride in response.json["rides"]))
        reasons = {ride["provider"]: ride["fare_unavailable_reason"] for ride in response.json["rides"]}
        self.assertIn("UBER_SERVER_TOKEN", reasons["Uber"])
        self.assertIn("OLA_APP_TOKEN", reasons["Ola"])
        self.assertIn("Route distance", reasons["Rapido"])
        self.assertIn("Route distance", reasons["Namma Yatri"])
        self.assertIn("rate-card estimates", response.json["notice"])

    def test_booking_links_are_https_on_provider_domains(self):
        response = self.client.post("/api/rides/compare", json={
            "pickup": "Indiranagar", "destination": "MG Road",
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
        self.assertTrue(uber["booking"]["prefilled"])
        ola = next(r for r in response.json["rides"] if r["provider"] == "Ola")
        self.assertIn("12.975600", unquote(ola["booking_url"]))
        self.assertIn("12.978400", unquote(ola["booking_url"]))
        self.assertTrue(ola["booking"]["prefilled"])
        rapido = next(r for r in response.json["rides"] if r["provider"] == "Rapido")
        self.assertFalse(rapido["booking"]["prefilled"])
        namma_yatri = next(r for r in response.json["rides"] if r["provider"] == "Namma Yatri")
        self.assertEqual(namma_yatri["booking"]["url"], "https://nammayatri.in/")
        self.assertFalse(namma_yatri["booking"]["prefilled"])

    def test_invalid_coordinates_are_rejected(self):
        response = self.client.post("/api/rides/compare", json={
            "pickup": "A", "destination": "B", "pickup_coords": {"lat": 999, "lng": 0}})
        self.assertEqual(response.status_code, 400)

    def test_rapido_configured_link_template_receives_selected_route(self):
        with patch.dict("os.environ", {"RAPIDO_LINK_TEMPLATE":
            "https://www.rapido.bike/ride?from={pickup_lat},{pickup_lng}&to={drop_lat},{drop_lng}&pickup={pickup_text}&drop={drop_text}"}):
            response = self.client.post("/api/rides/compare", json={
                "pickup": "Indiranagar", "destination": "MG Road",
                "pickup_coords": {"lat": 12.9784, "lng": 77.6408},
                "destination_coords": {"lat": 12.9756, "lng": 77.6066},
            })
        rapido = next(ride for ride in response.json["rides"] if ride["provider"] == "Rapido")
        link = unquote(rapido["booking_url"])
        self.assertIn("12.978400,77.640800", link)
        self.assertIn("12.975600,77.606600", link)
        self.assertIn("Indiranagar", link)
        self.assertIn("MG Road", link)

    def test_route_metrics_generate_estimates_for_all_providers_without_api_credentials(self):
        response = self.client.post("/api/rides/compare", json={"pickup": "A", "destination": "B",
            "route_metrics": {"distance_km": 3, "duration_minutes": 9}})
        self.assertEqual(response.status_code, 200)
        estimates = [ride for ride in response.json["rides"] if ride["fare_status"] == "estimated"]
        self.assertEqual(
            {ride["provider"] for ride in estimates},
            {"Uber", "Ola", "Rapido", "Namma Yatri"},
        )
        self.assertTrue(all(ride["currency"] == "INR" and ride["fare_low"] < ride["fare_high"] for ride in estimates))
        self.assertTrue(all(ride["fare"] is None for ride in response.json["rides"] if ride["fare_status"] == "unavailable"))

    def test_invalid_route_metrics_are_rejected(self):
        for bad in ({"distance_km": -1, "duration_minutes": 5}, {"distance_km": 9999, "duration_minutes": 5}, {"x": 1}):
            r = self.client.post("/api/rides/compare", json={"pickup": "A", "destination": "B", "route_metrics": bad})
            self.assertEqual(r.status_code, 400)

    def test_provider_status_is_transparent(self):
        response = self.client.get("/api/providers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {provider["id"]: provider["status"] for provider in response.json["providers"]},
            {
                "uber": "requires_approval",
                "rapido": "estimated",
                "ola": "requires_credentials",
                "namma-yatri": "estimated",
            },
        )

    def test_cors_accepts_both_local_frontend_hosts(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = self.client.get("/api/health", headers={"Origin": origin})
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)


if __name__ == "__main__":
    unittest.main()

class FreeRoutingTests(unittest.TestCase):
    def test_osm_lookup_is_used_when_browser_sends_no_metrics(self):
        found = {"metrics": {"distance_km": 9.4, "duration_minutes": 31},
                 "pickup": {"lat": 12.9, "lng": 77.6}, "destination": {"lat": 12.96, "lng": 77.7}}
        with patch("cabcompare.backend.app.osm_route_metrics", return_value=found):
            client = create_app().test_client()
            response = client.post("/api/rides/compare", json={"pickup": "A", "destination": "B"})
        self.assertEqual(response.json["fare_source"], "estimated")
        self.assertEqual(response.json["route_metrics"]["distance_km"], 9.4)
        uber = next(r for r in response.json["rides"] if r["provider"] == "Uber")
        self.assertIn("12.96", unquote(uber["booking_url"]))
