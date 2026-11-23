import unittest

from cabcompare.backend.services.comparison import InvalidRoute, compare_rides


RIDES = [
    {"id": "uber-auto", "provider": "Uber", "ride_type": "auto", "fare": 120, "currency": "INR", "quoteType": "LIVE_QUOTE", "fare_status": "live", "availability_status": "available", "pickup_eta_minutes": 7, "trip_duration_minutes": 20},
    {"id": "rapido-bike", "provider": "Rapido", "ride_type": "bike", "fare": 65, "currency": "INR", "quoteType": "LIVE_QUOTE", "fare_status": "live", "availability_status": "available", "pickup_eta_minutes": 3, "trip_duration_minutes": 24},
    {"id": "ola-auto", "provider": "Ola", "ride_type": "auto", "fare": 100, "currency": "INR", "quoteType": "LIVE_QUOTE", "fare_status": "live", "availability_status": "available", "pickup_eta_minutes": 10, "trip_duration_minutes": 19},
]


class ComparisonTests(unittest.TestCase):
    def test_sorts_by_fare_and_marks_lowest_comparable_result(self):
        result = compare_rides("Central Station", "City Mall", RIDES)
        self.assertEqual([ride["fare"] for ride in result["rides"]], [65, 100, 120])
        self.assertEqual([ride["id"] for ride in result["rides"] if ride["is_lowest"]], ["rapido-bike"])
        self.assertEqual(result["fare_source"], "live")
        self.assertEqual(result["cheapest_quote"]["id"], "rapido-bike")

    def test_filters_categories_and_sorts_by_pickup(self):
        result = compare_rides("A", "B", RIDES, category="auto", sort="pickup")
        self.assertEqual([ride["id"] for ride in result["rides"]], ["uber-auto", "ola-auto"])

    def test_does_not_claim_lowest_across_different_fare_sources(self):
        rides = [dict(RIDES[0]), dict(RIDES[1], quoteType="FARE_ESTIMATE", fare_status="estimated")]
        result = compare_rides("A", "B", rides)
        self.assertFalse(any(ride["is_lowest"] for ride in result["rides"]))
        self.assertEqual(result["fare_source"], "mixed")

    def test_unavailable_quotes_never_win_lowest_quote(self):
        rides = [
            dict(RIDES[0], quoteType="UNAVAILABLE", fare_status="unavailable", availability_status="unknown", fare=None, currency=None),
            dict(RIDES[1], quoteType="FARE_ESTIMATE", fare_status="estimated"),
            dict(RIDES[2], quoteType="FARE_ESTIMATE", fare_status="estimated"),
        ]
        result = compare_rides("A", "B", rides)
        self.assertEqual([ride["id"] for ride in result["rides"] if ride["is_lowest"]], ["rapido-bike"])
        self.assertEqual(result["cheapest_quote"]["provider"], "Rapido")

    def test_keeps_multiple_products_for_the_same_provider_and_vehicle_type(self):
        rides = [dict(RIDES[0]), dict(RIDES[0], id="uber-auto-x", fare=135)]
        result = compare_rides("A", "B", rides)
        self.assertEqual(len(result["rides"]), 2)

    def test_cheapest_sort_keeps_a_zero_fare_first(self):
        rides = [dict(RIDES[0], fare=0), dict(RIDES[1], fare=1)]
        result = compare_rides("A", "B", rides)
        self.assertEqual([ride["fare"] for ride in result["rides"]], [0, 1])

    def test_rejects_empty_or_identical_locations(self):
        with self.assertRaises(InvalidRoute):
            compare_rides(" ", "B", RIDES)
        with self.assertRaises(InvalidRoute):
            compare_rides("Same", "same", RIDES)


if __name__ == "__main__":
    unittest.main()
