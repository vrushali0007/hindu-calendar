# src/cli.py
import argparse
from pathlib import Path
from uuid import uuid4
from datetime import timedelta
from icalendar import Calendar, Event

from .astronomy import events_for_year  # <-- uses real tithi-at-sunrise logic

def ensure_site_dir():
    Path("site").mkdir(parents=True, exist_ok=True)

def build_ics(events, prodid="-//Hindu Calendar (Location-aware)//vrushali//EN"):
    cal = Calendar()
    cal.add("prodid", prodid)
    cal.add("version", "2.0")
    for e in events:
        ev = Event()
        ev.add("uid", f"{uuid4()}@hinducalendar")
        ev.add("summary", e["summary"])
        ev.add("dtstart", e["date"])                 # all-day event
        ev.add("dtend", e["date"] + timedelta(days=1))
        ev.add("description", e.get("desc", ""))
        cal.add_component(ev)
    return cal.to_ical()

def main():
    ap = argparse.ArgumentParser(
        description="Generate Ekadashi & Chaturthi .ics using tithi-at-local-sunrise."
    )
    ap.add_argument("--lat", type=float, required=True, help="Latitude (decimal)")
    ap.add_argument("--lon", type=float, required=True, help="Longitude (decimal)")
    ap.add_argument("--year", type=int, required=True, help="Target calendar year, e.g., 2025")
    ap.add_argument("--outfile", type=str, default=None, help="Output .ics file path")
    args = ap.parse_args()

    ensure_site_dir()
    events = events_for_year(args.lat, args.lon, args.year)
    ics_bytes = build_ics(events)

    out = Path(args.outfile) if args.outfile else Path(f"site/{args.year}-ekadashi-chaturthi.ics")
    out.write_bytes(ics_bytes)
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
