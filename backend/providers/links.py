"""Truthful booking deep-link builders.

Every URL uses HTTPS on the provider's official domain (or Android app package
intent metadata). Only Uber (m.uber.com/looking) and Ola (book.olacabs.com)
support route parameter prefilling without proprietary agreements. Rapido and
Namma Yatri do not support public route prefill and explicitly report
prefilled=False / prefills_route=False.
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

ANDROID_PACKAGES = {
    "uber": "com.ubercab",
    "ola": "com.olacabs.customer",
    "rapido": "com.rapido.passenger",
    "namma yatri": "in.juspay.nammayatri",
}


def _has_coords(place: dict[str, Any]) -> bool:
    return place.get("lat") is not None and place.get("lng") is not None


def uber_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Uber universal link (m.uber.com/looking). Pickup and drop arrive pre-filled."""
    pickup, drop = route["pickup"], route["destination"]
    if not (_has_coords(pickup) and _has_coords(drop)):
        return {
            "url": "https://m.uber.com/",
            "prefilled": False,
            "prefills_route": False,
            "open_mode": "home_screen",
            "android_package": ANDROID_PACKAGES["uber"],
        }

    def place(p: dict[str, Any]) -> str:
        return json.dumps({
            "latitude": round(p["lat"], 6),
            "longitude": round(p["lng"], 6),
            "addressLine1": p["text"].split(",")[0],
            "addressLine2": p["text"],
        }, separators=(",", ":"))

    params = {"pickup": place(pickup), "drop[0]": place(drop)}
    client_id = os.getenv("UBER_CLIENT_ID")
    if client_id:
        params["client_id"] = client_id
    return {
        "url": "https://m.uber.com/looking?" + urlencode(params),
        "prefilled": True,
        "prefills_route": True,
        "open_mode": "prefilled_route",
        "android_package": ANDROID_PACKAGES["uber"],
    }


def ola_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Ola web booking link (book.olacabs.com). Pickup and drop arrive pre-filled."""
    pickup, drop = route["pickup"], route["destination"]
    if not (_has_coords(pickup) and _has_coords(drop)):
        return {
            "url": "https://book.olacabs.com/",
            "prefilled": False,
            "prefills_route": False,
            "open_mode": "home_screen",
            "android_package": ANDROID_PACKAGES["ola"],
        }
    params = {
        "serviceType": "p2p",
        "lat": f"{pickup['lat']:.6f}",
        "lng": f"{pickup['lng']:.6f}",
        "pickup": pickup["text"],
        "drop_lat": f"{drop['lat']:.6f}",
        "drop_lng": f"{drop['lng']:.6f}",
        "drop": drop["text"],
    }
    utm_source = os.getenv("OLA_AFFILIATE_UTM_SOURCE", "").strip()
    if utm_source:
        params["utm_source"] = utm_source
    category = _OLA_CATEGORIES.get((ride_type or "").casefold())
    if category:
        params["category"] = category
    return {
        "url": "https://book.olacabs.com/?" + urlencode(params),
        "prefilled": True,
        "prefills_route": True,
        "open_mode": "prefilled_route",
        "android_package": ANDROID_PACKAGES["ola"],
    }


def rapido_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Rapido has no documented public web prefill link unless RAPIDO_LINK_TEMPLATE is set."""
    template = os.getenv("RAPIDO_LINK_TEMPLATE", "").strip()
    pickup, drop = route["pickup"], route["destination"]
    if template and _has_coords(pickup) and _has_coords(drop):
        url = template.format(
            pickup_lat=f"{pickup['lat']:.6f}",
            pickup_lng=f"{pickup['lng']:.6f}",
            drop_lat=f"{drop['lat']:.6f}",
            drop_lng=f"{drop['lng']:.6f}",
            pickup_text=quote(pickup["text"]),
            drop_text=quote(drop["text"]),
        )
        return {
            "url": url,
            "prefilled": True,
            "prefills_route": True,
            "open_mode": "prefilled_route",
            "android_package": ANDROID_PACKAGES["rapido"],
        }
    return {
        "url": "https://www.rapido.bike/",
        "prefilled": False,
        "prefills_route": False,
        "open_mode": "home_screen",
        "android_package": ANDROID_PACKAGES["rapido"],
    }


def namma_yatri_link(route: dict[str, Any], ride_type: str | None = None) -> dict[str, Any]:
    """Namma Yatri does not support public URL route prefilling; opens homepage."""
    return {
        "url": "https://nammayatri.in/",
        "prefilled": False,
        "prefills_route": False,
        "open_mode": "home_screen",
        "android_package": ANDROID_PACKAGES["namma yatri"],
    }


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
