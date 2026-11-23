import unittest

from cabcompare.backend.services import routing


def fake_fetch(url):
    if "nominatim" in url:
        return [{"lat": "12.9716", "lon": "77.5946"}]
    return {"routes": [{"distance": 8000, "duration": 1200}]}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        routing._sleep = lambda _s: None

    def test_geocodes_text_then_routes(self):
        found = routing.osm_route_metrics("MG Road", None, "Indiranagar", None, fetch=fake_fetch)
        self.assertEqual(found["metrics"]["distance_km"], 8.0)
        self.assertEqual(found["metrics"]["duration_minutes"], 25)  # 20 min x 1.25 traffic allowance

    def test_uses_given_coordinates_without_geocoding(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return fake_fetch(url)
        pickup = {"lat": 12.9, "lng": 77.6}
        routing.osm_route_metrics("x", pickup, "y", {"lat": 12.95, "lng": 77.65}, fetch=fetch)
        self.assertEqual(len(calls), 1)

    def test_failures_return_none(self):
        def broken(url):
            raise OSError("network down")
        self.assertIsNone(routing.osm_route_metrics("A", None, "B", None, fetch=broken))
        self.assertIsNone(routing.osm_route_metrics("A", None, "B", None, fetch=lambda u: []))

    def test_suggest_places_parses_photon_and_local_hubs(self):
        def photon_fetch(url):
            if "photon.komoot.io" in url:
                return {
                    "features": [{
                        "geometry": {"coordinates": [77.6408, 12.9784]},
                        "properties": {
                            "osm_type": "N",
                            "osm_id": 123,
                            "name": "Indiranagar Metro Station",
                            "city": "Bengaluru",
                            "state": "Karnataka",
                            "countrycode": "IN",
                        },
                    }]
                }
            return []

        items = routing.suggest_places("Indira", fetch=photon_fetch)
        self.assertTrue(any("Indiranagar" in item["text"] for item in items))
        self.assertTrue(all("lat" in item and "lng" in item for item in items))

    def test_reverse_geocode_parses_photon_response(self):
        def photon_reverse(url):
            return {
                "features": [{
                    "geometry": {"coordinates": [77.6408, 12.9784]},
                    "properties": {
                        "osm_type": "W",
                        "osm_id": 456,
                        "name": "100 Feet Road",
                        "locality": "Indiranagar",
                        "city": "Bengaluru",
                        "state": "Karnataka",
                        "countrycode": "IN",
                    },
                }]
            }

        label = routing.reverse_geocode(12.9784, 77.6408, fetch=photon_reverse)
        self.assertEqual(label, "100 Feet Road, Indiranagar, Bengaluru, Karnataka")


if __name__ == "__main__":
    unittest.main()
