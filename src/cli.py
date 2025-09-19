# src/cli.py
import argparse
from pathlib import Path
from uuid import uuid4
from datetime import timedelta
from icalendar import Calendar, Event

from .astronomy import events_for_year

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

def main():
    ap = argparse.ArgumentParser(
        description="Generate location-aware Hindu calendar (.ics): Ekadashi (Smārta/Vaishnava), Sankashti, Amavasya/Purnima, Rahu Kaal."
    )
    ap.add_argument("--lat", type=float, required=True, help="Latitude (decimal)")
    ap.add_argument("--lon", type=float, required=True, help="Longitude (decimal)")
    ap.add_argument("--year", type=int, required=True, help="Target year, e.g., 2025")
    ap.add_argument("--tradition", choices=["smartha", "vaishnava"], default="smartha",
                    help="Ekadashi rule set (default: smartha)")
    ap.add_argument("--no-sankashti", action="store_true", help="Exclude Sankashti Chaturthi")
    ap.add_argument("--no-ap", action="store_true", help="Exclude Amavasya & Purnima")
    ap.add_argument("--no-rahukaal", action="store_true", help="Exclude Rahu Kaal")
    ap.add_argument("--outfile", type=str, default=None, help="Output .ics file path")
    args = ap.parse_args()

    ensure_site_dir()
    events = events_for_year(
        args.lat, args.lon, args.year,
        tradition=args.tradition,
        include_sankashti=not args.no_sankashti,
        include_amavasya_purnima=not args.no_ap,
        include_rahukaal=not args.no_rahukaal,
    )
    ics = build_ics(events)

    out = Path(args.outfile) if args.outfile else Path(
        f"site/{args.year}-fullcalendar-{args.tradition}.ics"
    )
    out.write_bytes(ics)
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
