"""Booking link builders.

Every URL here is an https link on the provider's own domain, so on a phone
with the app installed the OS can hand it to the app, and on desktop it opens
the provider's website. Only Uber (m.uber.com/looking) and Ola (book.olacabs.com)
accept pre-filled route parameters. Rapido and Namma Yatri have no public web
route-prefill link, so those open the provider's official page.

Verify each format against the provider's current docs before production use,
and edit ONLY this file if a provider changes its link scheme.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote, urlencode

_OLA_CATEGORIES = {
    "bike": "bike",
    "auto": "auto",
    "sedan": "prime_sedan",
    "premium": "prime_suv",
}


def _has_coords(place: dict[str, Any]) -> bool:
    return place.get("lat") is not None and place.get("lng") is not None


def uber_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Uber universal link (m.uber.com/looking). Pickup and drop arrive pre-filled."""
    pickup, drop = route["pickup"], route["destination"]
    if not (_has_coords(pickup) and _has_coords(drop)):
        return {"url": "https://m.uber.com/", "prefilled": False}

    def place(p: dict[str, Any]) -> str:
        return json.dumps({
            "latitude": round(p["lat"], 6), "longitude": round(p["lng"], 6),
            "addressLine1": p["text"].split(",")[0], "addressLine2": p["text"],
        }, separators=(",", ":"))

    params = {"pickup": place(pickup), "drop[0]": place(drop)}
    client_id = os.getenv("UBER_CLIENT_ID")
    if client_id:
        params["client_id"] = client_id
    return {"url": "https://m.uber.com/looking?" + urlencode(params), "prefilled": True}


def ola_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Ola web booking link (book.olacabs.com). Pickup and drop arrive pre-filled."""
    pickup, drop = route["pickup"], route["destination"]
    if not (_has_coords(pickup) and _has_coords(drop)):
        return {"url": "https://book.olacabs.com/", "prefilled": False}
    params = {
        "serviceType": "p2p",
        "lat": f"{pickup['lat']:.6f}", "lng": f"{pickup['lng']:.6f}", "pickup": pickup["text"],
        "drop_lat": f"{drop['lat']:.6f}", "drop_lng": f"{drop['lng']:.6f}", "drop": drop["text"],
    }
    category = _OLA_CATEGORIES.get((ride_type or "").casefold())
    if category:
        params["category"] = category
    return {"url": "https://book.olacabs.com/?" + urlencode(params), "prefilled": True}


def rapido_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Rapido has no documented public web prefill link. Set RAPIDO_LINK_TEMPLATE in .env
    with placeholders {pickup_lat} {pickup_lng} {drop_lat} {drop_lng} {pickup_text} {drop_text}."""
    template = os.getenv("RAPIDO_LINK_TEMPLATE")
    pickup, drop = route["pickup"], route["destination"]
    if template and _has_coords(pickup) and _has_coords(drop):
        url = template.format(
            pickup_lat=f"{pickup['lat']:.6f}", pickup_lng=f"{pickup['lng']:.6f}",
            drop_lat=f"{drop['lat']:.6f}", drop_lng=f"{drop['lng']:.6f}",
            pickup_text=quote(pickup["text"]), drop_text=quote(drop["text"]),
        )
        return {"url": url, "prefilled": True}
    return {"url": "https://www.rapido.bike/", "prefilled": False}


def namma_yatri_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    return {"url": "https://nammayatri.in/", "prefilled": False}


BUILDERS = {
    "uber": uber_link,
    "ola": ola_link,
    "rapido": rapido_link,
    "namma yatri": namma_yatri_link,
}


def booking_for(provider: str, route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any] | None:
    builder = BUILDERS.get(provider.casefold())
    if not builder:
        return None
    return {"provider": provider, **builder(route, ride_type)}
