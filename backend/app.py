import os
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from .providers import PROVIDERS
from .providers.links import booking_for
from .services.comparison import InvalidRoute, compare_rides, parse_metrics, validate_route
from .services.fares import comparison_rides
from .services.guards import SlidingWindowLimiter
from .services.routing import osm_route_metrics, reverse_geocode, suggest_places

load_dotenv()


def parse_coords(value):
    """Return {'lat','lng'} from a request value, None if absent, ValueError if invalid."""
    if value is None:
        return None
    try:
        lat, lng = float(value["lat"]), float(value["lng"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Coordinates must look like {\"lat\": 12.97, \"lng\": 77.59}.")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Coordinates are out of range.")
    return {"lat": lat, "lng": lng}


def _optional_near_coords():
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if lat is None or lng is None:
        return None
    return parse_coords({"lat": lat, "lng": lng})


def _client_key() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "local"


_LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    compare_limit = int(os.getenv("RATE_LIMIT_COMPARE_PER_MIN", "30"))
    places_limit = int(os.getenv("RATE_LIMIT_PLACES_PER_MIN", "90"))
    compare_limiter = SlidingWindowLimiter(max_requests=compare_limit, window_seconds=60.0)
    places_limiter = SlidingWindowLimiter(max_requests=places_limit, window_seconds=60.0)

    frontend_origins = {
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    }

    @app.after_request
    def add_security_and_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin and (origin in frontend_origins or _LOCAL_ORIGIN_RE.fullmatch(origin)):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    def _enforce_rate_limit(limiter: SlidingWindowLimiter):
        if limiter.max_requests <= 0:
            return None
        allowed, retry_after = limiter.allow(_client_key())
        if not allowed:
            resp = jsonify({
                "error": f"Too many requests. Try again in {retry_after} seconds.",
                "retry_after_seconds": retry_after,
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(retry_after)
            return resp
        return None

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "fare_mode": "hybrid"})

    @app.get("/api/providers")
    def providers():
        return jsonify({"providers": PROVIDERS, "fare_mode": "hybrid"})

    @app.get("/api/places/suggest")
    def place_suggestions():
        if limited := _enforce_rate_limit(places_limiter):
            return limited
        query = (request.args.get("q") or "").strip()
        if len(query) < 2 or len(query) > 160:
            return jsonify({"suggestions": [], "source": "openstreetmap"})
        try:
            near = _optional_near_coords()
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        return jsonify({
            "suggestions": suggest_places(query, near=near),
            "source": "openstreetmap",
        })

    @app.get("/api/places/reverse")
    def place_reverse():
        if limited := _enforce_rate_limit(places_limiter):
            return limited
        try:
            coords = parse_coords({"lat": request.args.get("lat"), "lng": request.args.get("lng")})
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        label = reverse_geocode(coords["lat"], coords["lng"])
        return jsonify({
            "text": label or f"Current location ({coords['lat']:.4f}, {coords['lng']:.4f})",
            **coords,
        })

    @app.get("/api/routes/popular")
    def popular_routes():
        return jsonify({
            "routes": [
                {"pickup": "Indiranagar, Bengaluru", "destination": "MG Road, Bengaluru"},
                {"pickup": "Bandra, Mumbai", "destination": "Lower Parel, Mumbai"},
                {"pickup": "Connaught Place, Delhi", "destination": "Hauz Khas, Delhi"},
            ],
            "source": "demo",
        })

    @app.post("/api/rides/compare")
    def compare():
        if limited := _enforce_rate_limit(compare_limiter):
            return limited
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send pickup and destination as JSON."}), 400
        try:
            metrics = parse_metrics(payload.get("route_metrics"))
            pickup_coords = parse_coords(payload.get("pickup_coords"))
            destination_coords = parse_coords(payload.get("destination_coords"))
            pickup_text, destination_text = validate_route(payload.get("pickup"), payload.get("destination"))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        route_geometry = None
        if (metrics is None or pickup_coords is None or destination_coords is None) and (
            isinstance(pickup_text, str) and isinstance(destination_text, str)
            and pickup_text.strip() and destination_text.strip()
            and pickup_text.strip().casefold() != destination_text.strip().casefold()
        ):
            found = osm_route_metrics(pickup_text.strip(), pickup_coords, destination_text.strip(), destination_coords)
            if found:
                metrics = metrics or found["metrics"]
                pickup_coords = pickup_coords or found["pickup"]
                destination_coords = destination_coords or found["destination"]
                route_geometry = found.get("geometry")
        try:
            result = compare_rides(
                pickup_text,
                destination_text,
                comparison_rides(pickup_coords, destination_coords, metrics),
                category=payload.get("category", "all"),
                sort=payload.get("sort", "cheapest"),
            )
        except InvalidRoute as error:
            return jsonify({"error": str(error)}), 400
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        link_route = {
            "pickup": {"text": result["route"]["pickup"], **(pickup_coords or {})},
            "destination": {"text": result["route"]["destination"], **(destination_coords or {})},
        }
        for ride in result["rides"]:
            booking = booking_for(ride["provider"], link_route, ride.get("ride_type"))
            ride["booking"] = booking
            ride["booking_url"] = booking["url"] if booking else None
        result["notice"] = (
            "Prices combine live provider API/ONDC quotes when configured with calibrated "
            "Indian city rate-card estimates using OpenStreetMap road distance and traffic duration. "
            "Confirm final surge and promos inside the provider app before booking."
        )
        result["route_metrics"] = metrics
        result["route_geometry"] = route_geometry
        if pickup_coords and destination_coords:
            result["route_coords"] = {"pickup": pickup_coords, "destination": destination_coords}
        return jsonify(result)

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify({"error": "Request body is too large."}), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
