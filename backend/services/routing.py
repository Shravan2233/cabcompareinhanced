"""Free OpenStreetMap location search, reverse geocoding, and OSRM road routing (no API key).

Uses Komoot Photon (OSM search-as-you-type) as primary geocoder, OpenStreetMap Nominatim
as fallback, a compact offline Indian city-hub table for resilience, and OSRM for real
driving distance, duration, and route geometry.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

from .comparison import parse_metrics

USER_AGENT = "CabCompare/1.0 (https://github.com/cabcompare)"
TRAFFIC_FACTOR = 1.25  # OSRM durations ignore urban congestion; apply city traffic allowance
INDIA_BBOX = "68.1,6.5,97.4,37.1"
INDIA_CENTER = {"lat": 20.5937, "lng": 78.9629}
_sleep = time.sleep

# Major Indian transit hubs and neighborhoods used as a fast local fallback/boost.
INDIAN_LANDMARKS: tuple[tuple[str, str, float, float], ...] = (
    ("Indiranagar", "Bengaluru, Karnataka", 12.9784, 77.6408),
    ("MG Road", "Bengaluru, Karnataka", 12.9756, 77.6066),
    ("Koramangala", "Bengaluru, Karnataka", 12.9352, 77.6245),
    ("Whitefield", "Bengaluru, Karnataka", 12.9698, 77.7500),
    ("Electronic City", "Bengaluru, Karnataka", 12.8452, 77.6602),
    ("Majestic / Kempegowda Bus Station", "Bengaluru, Karnataka", 12.9767, 77.5713),
    ("Kempegowda International Airport", "Bengaluru, Karnataka", 13.1986, 77.7066),
    ("HSR Layout", "Bengaluru, Karnataka", 12.9121, 77.6446),
    ("Jayanagar", "Bengaluru, Karnataka", 12.9299, 77.5824),
    ("Hebbal", "Bengaluru, Karnataka", 13.0358, 77.5970),
    ("Bandra", "Mumbai, Maharashtra", 19.0596, 72.8295),
    ("Lower Parel", "Mumbai, Maharashtra", 18.9977, 72.8376),
    ("Andheri West", "Mumbai, Maharashtra", 19.1363, 72.8277),
    ("Bandra Kurla Complex (BKC)", "Mumbai, Maharashtra", 19.0653, 72.8682),
    ("Chhatrapati Shivaji Maharaj International Airport", "Mumbai, Maharashtra", 19.0896, 72.8656),
    ("Colaba", "Mumbai, Maharashtra", 18.9067, 72.8147),
    ("Powai", "Mumbai, Maharashtra", 19.1176, 72.9060),
    ("Dadar", "Mumbai, Maharashtra", 19.0178, 72.8478),
    ("Connaught Place", "New Delhi, Delhi", 28.6315, 77.2167),
    ("Hauz Khas", "New Delhi, Delhi", 28.5494, 77.2001),
    ("Indira Gandhi International Airport", "New Delhi, Delhi", 28.5562, 77.1000),
    ("New Delhi Railway Station", "New Delhi, Delhi", 28.6429, 77.2191),
    ("Cyber City", "Gurugram, Haryana", 28.4950, 77.0895),
    ("Sector 18", "Noida, Uttar Pradesh", 28.5708, 77.3261),
    ("Hitech City", "Hyderabad, Telangana", 17.4435, 78.3772),
    ("Gachibowli", "Hyderabad, Telangana", 17.4401, 78.3489),
    ("Banjara Hills", "Hyderabad, Telangana", 17.4156, 78.4347),
    ("Rajiv Gandhi International Airport", "Hyderabad, Telangana", 17.2403, 78.4294),
    ("T. Nagar", "Chennai, Tamil Nadu", 13.0418, 80.2341),
    ("Adyar", "Chennai, Tamil Nadu", 13.0012, 80.2565),
    ("Chennai Central", "Chennai, Tamil Nadu", 13.0827, 80.2707),
    ("Hinjewadi", "Pune, Maharashtra", 18.5913, 73.7389),
    ("Koregaon Park", "Pune, Maharashtra", 18.5362, 73.8940),
    ("Park Street", "Kolkata, West Bengal", 22.5519, 88.3532),
    ("Salt Lake Sector V", "Kolkata, West Bengal", 22.5735, 88.4331),
)


def _get_json(url: str, timeout: float = 3.5) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _in_india_bounds(lat: float, lng: float) -> bool:
    return 6.0 <= lat <= 37.5 and 68.0 <= lng <= 97.6


def _haversine_km(p1: dict[str, float], p2: dict[str, float]) -> float:
    radius = 6371.0
    lat1, lat2 = math.radians(p1["lat"]), math.radians(p2["lat"])
    dlat = lat2 - lat1
    dlng = math.radians(p2["lng"] - p1["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _format_photon_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    lng, lat = float(coords[0]), float(coords[1])
    code = str(props.get("countrycode") or "").upper()
    if code and code != "IN" and not _in_india_bounds(lat, lng):
        return None

    main = (
        props.get("name")
        or props.get("street")
        or props.get("locality")
        or props.get("city")
        or props.get("county")
    )
    if not main:
        return None
    parts = [
        props.get("locality") or props.get("district"),
        props.get("city") or props.get("county"),
        props.get("state"),
    ]
    seen = {main.casefold()}
    secondary_parts = []
    for part in parts:
        if isinstance(part, str) and part.strip() and part.strip().casefold() not in seen:
            seen.add(part.strip().casefold())
            secondary_parts.append(part.strip())
    secondary = ", ".join(secondary_parts) or "India"
    text = f"{main}, {secondary}" if secondary != "India" else main
    return {
        "id": f"osm-{props.get('osm_type', 'n')}-{props.get('osm_id', f'{lat:.4f}-{lng:.4f}')}",
        "main": main,
        "secondary": secondary,
        "text": text,
        "lat": round(lat, 6),
        "lng": round(lng, 6),
    }


def _format_nominatim_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat, lng = float(hit["lat"]), float(hit["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    display = str(hit.get("display_name") or "").strip()
    parts = [segment.strip() for segment in display.split(",") if segment.strip()] if display else []
    main = hit.get("name") or (parts[0] if parts else f"{lat:.4f}, {lng:.4f}")
    tail = [p for p in parts[1:] if p.casefold() not in {main.casefold(), "india"}]
    secondary = ", ".join(tail[:3]) or "India"
    return {
        "id": f"nom-{hit.get('place_id', f'{lat:.4f}-{lng:.4f}')}",
        "main": main,
        "secondary": secondary,
        "text": f"{main}, {secondary}" if secondary != "India" else main,
        "lat": round(lat, 6),
        "lng": round(lng, 6),
    }


def _match_local_landmarks(text: str, near: dict[str, float] | None = None) -> list[dict[str, Any]]:
    needle = " ".join(text.lower().replace(",", " ").split())
    if not needle:
        return []
    tokens = needle.split()
    matches: list[tuple[float, dict[str, Any]]] = []
    for index, (main, secondary, lat, lng) in enumerate(INDIAN_LANDMARKS):
        haystack = f"{main} {secondary}".lower()
        if all(token in haystack for token in tokens):
            score = 0.0 if main.lower().startswith(tokens[0]) else 1.0
            if near:
                score += _haversine_km(near, {"lat": lat, "lng": lng}) / 1000.0
            matches.append((
                score,
                {
                    "id": f"hub-{index}",
                    "main": main,
                    "secondary": secondary,
                    "text": f"{main}, {secondary}",
                    "lat": lat,
                    "lng": lng,
                },
            ))
    matches.sort(key=lambda item: item[0])
    return [item[1] for item in matches]


def _photon_search(query: str, near: dict[str, float] | None, limit: int, fetch: Callable) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "q": query,
        "bbox": INDIA_BBOX,
        "limit": str(limit),
        "lang": "en",
    }
    bias = near or INDIA_CENTER
    params["lat"] = f"{bias['lat']:.4f}"
    params["lon"] = f"{bias['lng']:.4f}"
    data = fetch("https://photon.komoot.io/api?" + urllib.parse.urlencode(params))
    features = data.get("features", []) if isinstance(data, dict) else []
    results = []
    for feature in features:
        parsed = _format_photon_feature(feature)
        if parsed:
            results.append(parsed)
    return results


def _nominatim_search(query: str, near: dict[str, float] | None, limit: int, fetch: Callable) -> list[dict[str, Any]]:
    params = {"q": query, "format": "jsonv2", "limit": str(limit), "countrycodes": "in", "addressdetails": "1"}
    if near:
        params["viewbox"] = f"{near['lng'] - 0.5},{near['lat'] + 0.5},{near['lng'] + 0.5},{near['lat'] - 0.5}"
    found = fetch("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params))
    if not isinstance(found, list):
        return []
    return [item for hit in found if (item := _format_nominatim_hit(hit)) is not None]


def suggest_places(
    query: str,
    near: dict[str, float] | None = None,
    limit: int = 6,
    fetch: Callable = _get_json,
) -> list[dict[str, Any]]:
    """Return Indian OSM place suggestions while typing (Photon + local hubs + Nominatim fallback)."""
    cleaned = " ".join(query.split())
    if len(cleaned) < 2:
        return []

    local_hits = _match_local_landmarks(cleaned, near=near)
    remote_hits: list[dict[str, Any]] = []
    try:
        remote_hits = _photon_search(cleaned, near=near, limit=limit + 2, fetch=fetch)
    except (OSError, ValueError, TypeError, KeyError):
        remote_hits = []

    if not remote_hits:
        try:
            remote_hits = _nominatim_search(cleaned, near=near, limit=limit, fetch=fetch)
        except (OSError, ValueError, TypeError, KeyError):
            remote_hits = []

    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Put exact local landmark hub matches first when no city bias narrowed remote hits,
    # otherwise prefer city-biased OSM results with local matches alongside.
    ordered = (remote_hits + local_hits) if near else (local_hits[:2] + remote_hits + local_hits[2:])
    for item in ordered:
        dedupe_key = f"{item['main'].casefold()}|{item['secondary'].split(',')[0].strip().casefold()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        combined.append(item)
        if len(combined) >= limit:
            break
    return combined


def geocode(text: str, near: dict[str, float] | None = None, fetch: Callable = _get_json) -> dict[str, float] | None:
    """Resolve a location string to {'lat', 'lng'} using OSM services."""
    if fetch is _get_json:
        local = _match_local_landmarks(text, near=near)
        normalized = " ".join(text.lower().replace(",", " ").split())
        if local:
            top = local[0]
            top_full = " ".join(f"{top['main']} {top['secondary']}".lower().replace(",", " ").split())
            has_city = any(c in normalized for c in ("bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "chennai", "pune", "kolkata", "gurugram", "noida"))
            if normalized == top_full or (normalized.startswith(top["main"].lower()) and has_city):
                return {"lat": top["lat"], "lng": top["lng"]}
        try:
            hits = _photon_search(text, near=near, limit=3, fetch=fetch)
            if hits:
                return {"lat": hits[0]["lat"], "lng": hits[0]["lng"]}
        except (OSError, ValueError, TypeError, KeyError):
            pass

    hits = _nominatim_search(text, near=near, limit=1, fetch=fetch)
    if hits:
        return {"lat": hits[0]["lat"], "lng": hits[0]["lng"]}

    if fetch is _get_json:
        local = _match_local_landmarks(text, near=near)
        if local:
            return {"lat": local[0]["lat"], "lng": local[0]["lng"]}
    return None


def reverse_geocode(lat: float, lng: float, fetch: Callable = _get_json) -> str | None:
    """Resolve coordinates to a readable place label via free OSM services."""
    try:
        data = fetch(f"https://photon.komoot.io/reverse?lat={lat:.6f}&lon={lng:.6f}&lang=en")
        features = data.get("features", []) if isinstance(data, dict) else []
        if features:
            parsed = _format_photon_feature(features[0])
            if parsed:
                return parsed["text"]
    except (OSError, ValueError, TypeError, KeyError):
        pass

    try:
        data = fetch(f"https://nominatim.openstreetmap.org/reverse?lat={lat:.6f}&lon={lng:.6f}&format=jsonv2")
        if isinstance(data, dict):
            parsed = _format_nominatim_hit(data)
            if parsed:
                return parsed["text"]
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def osm_route_metrics(pickup_text, pickup_coords, destination_text, destination_coords, fetch: Callable = _get_json):
    """Return {'metrics', 'pickup', 'destination', 'geometry'} or None."""
    try:
        origin = pickup_coords
        used_nominatim = False
        if origin is None:
            origin = geocode(pickup_text, fetch=fetch)
            used_nominatim = fetch is not _get_json
            if destination_coords is None and used_nominatim:
                _sleep(1.1)  # Nominatim allows about one request per second
        destination = destination_coords or geocode(destination_text, near=origin, fetch=fetch)
        if not origin or not destination:
            return None

        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{origin['lng']},{origin['lat']};{destination['lng']},{destination['lat']}"
            f"?overview=simplified&geometries=geojson"
        )
        try:
            route = fetch(url)["routes"][0]
            metrics = parse_metrics({
                "distance_km": route["distance"] / 1000,
                "duration_minutes": route["duration"] / 60 * TRAFFIC_FACTOR,
            })
            geometry = (route.get("geometry") or {}).get("coordinates") or [
                [origin["lng"], origin["lat"]],
                [destination["lng"], destination["lat"]],
            ]
            return {"metrics": metrics, "pickup": origin, "destination": destination, "geometry": geometry}
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            if fetch is not _get_json:
                return None
            # Road-distance fallback (1.35x straight-line, ~24 km/h urban speed) if OSRM demo server hiccups.
            straight_km = max(0.5, _haversine_km(origin, destination))
            road_km = min(500.0, round(straight_km * 1.35, 1))
            minutes = max(3, round((road_km / 24.0) * 60.0))
            return {
                "metrics": parse_metrics({"distance_km": road_km, "duration_minutes": minutes}),
                "pickup": origin,
                "destination": destination,
                "geometry": [[origin["lng"], origin["lat"]], [destination["lng"], destination["lat"]]],
            }
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
