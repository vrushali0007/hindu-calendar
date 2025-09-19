from fastapi import FastAPI, Request, Response, HTTPException
from typing import Optional
from datetime import datetime, timedelta
from hashlib import md5

import pytz
import requests
from icalendar import Calendar, Event

from src.astronomy import events_for_year

app = FastAPI(title="Hindu Calendar (Dynamic)")
UTC = pytz.utc


# ---------- helpers ----------
def stable_uid(e):
    if e.get("all_day", True):
        key = f"{e['summary']}|{e['date'].isoformat()}|ALLDAY"
    else:
        key = f"{e['summary']}|{e['date_start'].isoformat()}|{e['date_end'].isoformat()}"
    return f"{md5(key.encode()).hexdigest()}@hinducalendar"


def build_ics(events, calname="Hindu Calendar", tzid: Optional[str] = None) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Hindu Calendar (Dynamic)//vrushali//EN")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", calname)
    if tzid:
        cal.add("X-WR-TIMEZONE", tzid)

    for e in events:
        ev = Event()
        ev.add("uid", stable_uid(e))
        ev.add("summary", e["summary"])
        ev.add("description", e.get("desc", ""))

        if e.get("all_day", True):
            dt = e["date"]
            ev.add("dtstart", dt)
            ev.add("dtend", dt + timedelta(days=1))
        else:
            # store timed events in UTC so clients render in local time correctly
            ev.add("dtstart", e["date_start"].astimezone(UTC))
            ev.add("dtend",   e["date_end"].astimezone(UTC))

        cal.add_component(ev)
    return cal.to_ical()


def ip_geolocate() -> Optional[tuple[float, float]]:
    # Try ipinfo first, then ipapi
    try:
        r = requests.get("https://ipinfo.io/json", timeout=4)
        if r.ok and r.json().get("loc"):
            lat_s, lon_s = r.json()["loc"].split(",")
            return float(lat_s), float(lon_s)
    except Exception:
        pass
    try:
        r = requests.get("https://ipapi.co/json", timeout=4)
        if r.ok:
            return float(r.json()["latitude"]), float(r.json()["longitude"])
    except Exception:
        pass
    return None


def coalesce_rahukaal_for_viewer(events, viewer_tzid: str):
    """
    Ensure exactly one Rahu Kaal per viewer *calendar day* in viewer_tz.
    This avoids apparent 'missing' days due to UTC crossing day boundaries.
    """
    vt = pytz.timezone(viewer_tzid)
    rk = [e for e in events if not e.get("all_day", True) and e.get("summary") == "Rahu Kaal"]

    per_day = {}
    for e in rk:
        local_start = e["date_start"].astimezone(vt)
        key = local_start.date()
        per_day.setdefault(key, []).append(e)

    chosen = []
    for key, lst in per_day.items():
        lst.sort(key=lambda x: x["date_start"].astimezone(vt))
        chosen.append(lst[-1])  # keep the one that starts latest in that viewer day

    # drop all Rahu Kaal, replace with chosen
    others = [e for e in events if not (not e.get("all_day", True) and e.get("summary") == "Rahu Kaal")]
    others.extend(chosen)
    return others


# ---------- routes ----------
@app.get("/")
def index():
    return {
        "ok": True,
        "usage": "/calendar.ics?year=2025&year_to=2026 (auto-location by IP)",
        "params": {
            "lat/lon": "optional overrides",
            "tradition": "smartha|vaishnava",
            "viewer_tz": "e.g. Europe/Stockholm (used to coalesce Rahu Kaal per viewer day)",
            "festivals": "all or diwali,karwa_chauth,mahashivratri,gudi_padwa,ganesh_chaturthi,navaratri_start,guru_nanak",
            "include_sankashti": "true|false",
            "include_ap": "true|false (Amavasya/Purnima)",
            "include_rahukaal": "true|false",
            "include_festivals": "true|false",
        }
    }


@app.get("/calendar.ics")
def calendar(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    year: int = datetime.utcnow().year,
    year_to: Optional[int] = None,
    tradition: str = "smartha",
    viewer_tz: Optional[str] = None,
    festivals: str = "all",
    include_sankashti: bool = True,
    include_ap: bool = True,
    include_rahukaal: bool = True,
    include_festivals: bool = True,
):
    # Auto-locate if coords not provided
    if lat is None or lon is None:
        where = ip_geolocate()
        if not where:
            raise HTTPException(400, "Could not auto-detect location; pass ?lat=&lon=")
        lat, lon = where

    y2 = year_to or year

    # Build events for the range
    events = []
    for y in range(year, y2 + 1):
        events.extend(
            events_for_year(
                lat, lon, y,
                tradition=tradition,
                include_sankashti=include_sankashti,
                include_amavasya_purnima=include_ap,
                include_rahukaal=include_rahukaal,
                include_festivals=include_festivals,
                festivals_which=festivals,
            )
        )

    # Fix: coalesce Rahu Kaal by viewer timezone so there is exactly one per viewer day
    if viewer_tz:
        try:
            _ = pytz.timezone(viewer_tz)  # validate tz id
            events = coalesce_rahukaal_for_viewer(events, viewer_tz)
        except Exception:
            # ignore invalid tz; proceed without coalescing
            pass

    ics = build_ics(events, calname="Hindu Calendar", tzid=viewer_tz)
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "Cache-Control": "private, max-age=900"
    }
    return Response(content=ics, media_type="text/calendar", headers=headers)
