from fastapi import FastAPI, Request, Response, HTTPException
from typing import Optional
from datetime import datetime, timedelta
from icalendar import Calendar, Event
import pytz, requests
from hashlib import md5

from src.astronomy import events_for_year

app = FastAPI(title="Hindu Calendar (Dynamic)")
UTC = pytz.utc

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
            ev.add("dtstart", e["date_start"].astimezone(UTC))
            ev.add("dtend",   e["date_end"].astimezone(UTC))
        cal.add_component(ev)
    return cal.to_ical()

def ip_geolocate() -> Optional[tuple[float, float]]:
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

@app.get("/")
def index():
    return {
        "ok": True,
        "usage": "/calendar.ics?year=2025&year_to=2026 (auto-location by IP)",
        "params": {
            "lat/lon": "optional overrides",
            "tradition": "smartha|vaishnava",
            "viewer_tz": "e.g. Europe/Stockholm (label only)",
            "festivals": "all or diwali,karwa_chauth,mahashivratri,gudi_padwa,ganesh_chaturthi,navaratri_start,guru_nanak",
            "include_sankashti": "true|false",
            "include_ap": "true|false",
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
    if lat is None or lon is None:
        where = ip_geolocate()
        if not where:
            raise HTTPException(400, "Could not auto-detect location; pass ?lat=&lon=")
        lat, lon = where

    y2 = year_to or year
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

    ics = build_ics(events, calname="Hindu Calendar", tzid=viewer_tz)
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "Cache-Control": "private, max-age=900"
    }
    return Response(content=ics, media_type="text/calendar", headers=headers)
