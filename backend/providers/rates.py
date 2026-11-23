"""Approximate provider/vehicle rate cards for clearly labelled route estimates."""

# provider, vehicle, ride_type, base_fare, included_km, per_km, per_minute,
# minimum_fare, rate_multiplier
RATE_CARDS = [
    ("Rapido", "Bike taxi", "bike", 20, 0, 7, 0.5, 30, 1.00),
    ("Rapido", "Auto", "auto", 30, 2, 15, 0, 30, 1.05),
    ("Namma Yatri", "Auto", "auto", 30, 2, 15, 0, 30, 1.00),
]

LOW_FACTOR = 0.90
HIGH_FACTOR = 1.20
