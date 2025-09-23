"""Location utilities shared across CLI and server components."""
from __future__ import annotations

import requests


def autolocate() -> tuple[float, float]:
    """Best-effort IP geolocation returning ``(latitude, longitude)``.

    The helper first attempts to resolve the coordinates via ipinfo.io (which
    is fast and does not require an API key). If that fails for any reason it
    falls back to ipapi.co.  Errors from the fallback service are surfaced so
    callers can decide how to handle them.
    """

    try:
        response = requests.get("https://ipinfo.io/json", timeout=4)
        if response.ok and response.json().get("loc"):
            lat_s, lon_s = response.json()["loc"].split(",")
            return float(lat_s), float(lon_s)
    except Exception:
        # Swallow any errors from the primary provider so that we can attempt
        # the fallback service below.
        pass

    fallback = requests.get("https://ipapi.co/json", timeout=4)
    fallback.raise_for_status()
    data = fallback.json()
    return float(data["latitude"]), float(data["longitude"])
