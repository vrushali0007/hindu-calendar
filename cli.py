import argparse
from pathlib import Path
from hashlib import md5
from datetime import timedelta
from icalendar import Calendar, Event
import requests
import pytz
from typing import Optional

from .astronomy import events_for_year

UTC = pytz.utc

def coalesce_rahukaal_for_viewer(events, viewer_tzid: str):
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
        chosen.append(lst[-1])
    keep = [e for e in events if not (not e.get("all_day", True) and e.get("summary") == "Rahu Kaal")]
    keep.extend(chosen)
    return keep

def ensure_site_dir():
    Path("site").mkdir(parents=True, exist_ok=True)

def autolocate() -> tuple[float, float]:
    try:
        r = requests.get("https://ipinfo.io/json", timeout=4)
        if r.ok and r.json().get("loc"):
            lat_s, lon_s = r.json()["loc"].split(",")
            return float(lat_s), float(lon_s)
    except Exception:
        pass
    r = requests.get("https://ipapi.co/json", timeout=4)
    r.raise_for_status()
    return float(r.json()["latitude"]), float(r.json()["longitude"])

def stable_uid(e):
    if e.get("all_day", True):
        key = f"{e['summary']}|{e['date'].isoformat()}|ALLDAY"
    else:
        key = f"{e['summary']}|{e['date_start'].isoformat()}|{e['date_end'].isoformat()}"
    return f"{md5(key.encode()).hexdigest()}@hinducalendar"

def build_ics(events, prodid="-//Hindu Calendar (Location-aware)//vrushali//EN",
              calname="Hindu Calendar", tzid: Optional[str] = None):
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
            # store timed events in UTC, clients render in local tz
            ev.add("dtstart", e["date_start"].astimezone(UTC))
            ev.add("dtend",   e["date_end"].astimezone(UTC))
        cal.add_component(ev)
    return cal.to_ical()

def generate_range(lat, lon, year_from, year_to, **kw):
    all_events = []
    for y in range(year_from, year_to + 1):
        all_events.extend(events_for_year(lat, lon, y, **kw))
    return all_events

def main():
    ap = argparse.ArgumentParser(
        description="Hindu Calendar (.ics): Ekadashi (Smārta/Vaishnava), Sankashti, Amavasya/Purnima, Rahu Kaal, festivals — location-aware."
    )
    ap.add_argument("--lat", type=float, help="Latitude (decimal)")
    ap.add_argument("--lon", type=float, help="Longitude (decimal)")
    ap.add_argument("--auto-location", action="store_true", help="Detect lat/lon from IP")
    ap.add_argument("--year", type=int, required=True, help="Start year, e.g., 2025")
    ap.add_argument("--year-to", type=int, help="End year (inclusive). If omitted, equals --year.")
    ap.add_argument("--tradition", choices=["smartha", "vaishnava"], default="smartha")
    ap.add_argument("--no-sankashti", action="store_true")
    ap.add_argument("--no-ap", action="store_true")
    ap.add_argument("--no-rahukaal", action="store_true")
    ap.add_argument("--no-festivals", action="store_true")
    ap.add_argument("--festivals", type=str, default="all",
                    help='Comma list (default "all"): diwali, karwa_chauth, mahashivratri, gudi_padwa, ganesh_chaturthi, navaratri_start, guru_nanak')
    ap.add_argument("--viewer-tz", type=str,
                    help="Collapse timed events per viewer local date; e.g. 'Europe/Stockholm'")
    ap.add_argument("--outfile", type=str, default=None, help="Output .ics file path")
    args = ap.parse_args()

    if args.auto_location:
        if args.lat is not None or args.lon is not None:
            print("Note: --auto-location overrides --lat/--lon")
        try:
            args.lat, args.lon = autolocate()
        except Exception as e:
            raise SystemExit(f"Auto-location failed ({e}). Pass --lat and --lon.")

    if args.lat is None or args.lon is None:
        raise SystemExit("Provide --lat and --lon, or use --auto-location.")

    year_to = args.year_to or args.year
    ensure_site_dir()

    events = generate_range(
        args.lat, args.lon, args.year, year_to,
        tradition=args.tradition,
        include_sankashti=not args.no_sankashti,
        include_amavasya_purnima=not args.no_ap,
        include_rahukaal=not args.no_rahukaal,
        include_festivals=not args.no_festivals,
        festivals_which=args.festivals,
    )

    if args.viewer_tz:
        events = coalesce_rahukaal_for_viewer(events, args.viewer_tz)

    ics = build_ics(events, calname="Hindu Calendar", tzid=(args.viewer_tz or None))
    out = Path(args.outfile) if args.outfile else Path(
        f"site/{args.year}-{year_to}-hindu-calendar.ics" if year_to != args.year
        else f"site/{args.year}-hindu-calendar.ics"
    )
    out.write_bytes(ics)
    msg = f"Wrote {out}  (lat={args.lat}, lon={args.lon}, years={args.year}..{year_to})"
    if args.viewer_tz:
        msg += f"  [viewer-tz={args.viewer_tz}]"
    print(msg)

if __name__ == "__main__":
    main()
