# server/app.py
from datetime import timedelta
from pathlib import Path
from hashlib import md5
from typing import Optional

import pytz
from fastapi import FastAPI, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

# import your event generator
from src.astronomy import events_for_year

app = FastAPI(title="Hindu Calendar API")

# --------- helpers (ICS builder & Rahukaal coalescer) ---------
def stable_uid(e):
    if e.get("all_day", True):
        key = f"{e['summary']}|{e['date'].isoformat()}|ALLDAY"
    else:
        key = f"{e['summary']}|{e['date_start'].isoformat()}|{e['date_end'].isoformat()}"
    return f"{md5(key.encode()).hexdigest()}@hinducalendar"

def build_ics(events, prodid="-//Hindu Calendar (Location-aware)//vrushali//EN", calname="Hindu Calendar", tzid: Optional[str]=None):
    from icalendar import Calendar, Event  # lazy import
    cal = Calendar()
    cal.add("prodid", prodid)
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
            ev.add("dtstart", e["date_start"])
            ev.add("dtend",   e["date_end"])
        cal.add_component(ev)
    return cal.to_ical()

def coalesce_rahukaal_for_viewer(events, viewer_tzid: str):
    import pytz
    vt = pytz.timezone(viewer_tzid)
    rk = [e for e in events if not e.get("all_day", True) and e.get("summary") == "Rahu Kaal"]
    per = {}
    for e in rk:
        ds_v = e["date_start"].astimezone(vt)
        key = ds_v.date()
        per.setdefault(key, []).append(e)
    chosen = []
    for key, lst in per.items():
        lst.sort(key=lambda x: x["date_start"].astimezone(vt))
        chosen.append(lst[-1])  # keep latest start per viewer-day
    keep = [e for e in events if not (not e.get("all_day", True) and e.get("summary") == "Rahu Kaal")]
    keep.extend(chosen)
    return keep

# --------------------- routes ---------------------
@app.get("/", response_class=PlainTextResponse)
def root():
    return "Hindu Calendar API is running. Try /docs for the interactive UI."

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/ics")
def ics(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    year: int = Query(..., description="Start year, e.g. 2025"),
    year_to: Optional[int] = Query(None, description="End year (inclusive). If omitted, equals 'year'."),
    tradition: str = Query("smartha", pattern="^(smartha|vaishnava)$"),
    no_sankashti: bool = False,
    no_ap: bool = False,
    no_rahukaal: bool = False,
    no_festivals: bool = False,
    festivals: str = Query("all", description='Comma list or "all"'),
    viewer_tz: Optional[str] = Query(None, description="e.g. 'Europe/Stockholm'"),
):
    yf = year
    yt = year_to or year

    # collect events for the whole range
    all_events = []
    for y in range(yf, yt + 1):
        all_events.extend(
            events_for_year(
                lat, lon, y,
                tradition=tradition,
                include_sankashti=not no_sankashti,
                include_amavasya_purnima=not no_ap,
                include_rahukaal=not no_rahukaal,
                include_festivals=not no_festivals,
                festivals_which=festivals,
            )
        )

    # optional Rahu Kaal coalescing per viewer tz
    if viewer_tz:
        try:
            pytz.timezone(viewer_tz)  # validate
            all_events = coalesce_rahukaal_for_viewer(all_events, viewer_tz)
        except Exception:
            pass

    # build ics and return as download
    name = f"hindu-calendar-{yf}-{yt if yt!=yf else ''}{'' if yt!=yf else ''}.ics".replace("--", "-").strip("-")
    payload = build_ics(all_events, calname="Hindu Calendar", tzid=viewer_tz)
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return StreamingResponse(iter([payload]), media_type="text/calendar", headers=headers)