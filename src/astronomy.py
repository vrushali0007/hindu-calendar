# src/astronomy.py
from __future__ import annotations
from datetime import date, datetime, timedelta
from math import floor
from typing import List, Dict, Tuple

import pytz
from timezonefinder import TimezoneFinder
from astral import LocationInfo
from astral.sun import sun
from astral.moon import moonrise, moonset
from skyfield.api import load

# ======== Ephemeris cache ========
_eph = None
_ts = None
def _load_ephem():
    global _eph, _ts
    if _eph is None or _ts is None:
        _eph = load("de421.bsp")  # first run downloads once
        _ts = load.timescale()
    return _eph, _ts

# ======== Timezone & daily times ========
def iana_timezone_for(lat: float, lon: float):
    tzname = TimezoneFinder().timezone_at(lng=lon, lat=lat) or "UTC"
    return pytz.timezone(tzname)

def local_sun_times(lat: float, lon: float, day: date, tz) -> Tuple[datetime, datetime]:
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz.zone)
    sdict = sun(loc.observer, date=day, tzinfo=tz)
    return sdict["sunrise"], sdict["sunset"]  # both aware

def local_moonrise(lat: float, lon: float, day: date, tz):
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz.zone)
    try:
        return moonrise(loc.observer, date=day, tzinfo=tz)
    except Exception:
        return None

# ======== Tithi (Moon–Sun elongation) ========
def _ts_from_dt(dt_aware: datetime):
    eph, ts = _load_ephem()
    dt_utc = dt_aware.astimezone(pytz.utc)
    sec = dt_utc.second + dt_utc.microsecond / 1e6
    t = ts.utc(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, sec)
    return eph, ts, t

def _ecliptic_longitudes(dt_aware: datetime) -> Tuple[float, float]:
    eph, ts, t = _ts_from_dt(dt_aware)
    earth = eph["earth"]
    sun_app  = earth.at(t).observe(eph["sun"]).apparent()
    moon_app = earth.at(t).observe(eph["moon"]).apparent()
    _, lon_sun, _  = sun_app.ecliptic_latlon()
    _, lon_moon, _ = moon_app.ecliptic_latlon()
    return lon_sun.degrees % 360.0, lon_moon.degrees % 360.0

def tithi_number_at(dt_aware: datetime) -> int:
    lam_sun, lam_moon = _ecliptic_longitudes(dt_aware)
    diff = (lam_moon - lam_sun) % 360.0
    return int(floor(diff / 12.0)) + 1  # 1..30

def paksha_for_tithi(n: int) -> str:
    return "Shukla" if 1 <= n <= 15 else "Krishna"

# ======== Rahu Kaal (1/8 daytime segments) ========
# Standard segment mapping (1..8) per weekday
_RAHU_SEG = {  # Mon..Sun => segment index
    0: 2, 1: 7, 2: 5, 3: 6, 4: 4, 5: 3, 6: 8
}
# (Optional) Gulika, Yamaganda tables could live here too later.

def rahu_kaal_for_day(lat: float, lon: float, day: date, tz) -> Tuple[datetime, datetime]:
    sr, ss = local_sun_times(lat, lon, day, tz)
    daylen = (ss - sr).total_seconds()
    seg = _RAHU_SEG[day.weekday()]  # Monday=0
    seg_len = daylen / 8.0
    start = sr + timedelta(seconds= (seg - 1) * seg_len)
    end   = start + timedelta(seconds= seg_len)
    return start, end

# ======== Amavasya / Purnima detection ========
def is_amavasya_at_sunrise(sr: datetime) -> bool:
    return tithi_number_at(sr) == 30

def is_purnima_at_sunrise(sr: datetime) -> bool:
    return tithi_number_at(sr) == 15

# ======== Ekadashi rules ========
def ekadashi_events_for_year(lat: float, lon: float, year: int, tradition: str = "smartha") -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    ev: List[Dict] = []

    trad = (tradition or "smartha").lower()

    while d <= end:
        try:
            sr = local_sun_times(lat, lon, d, tz)[0]
        except Exception:
            d += timedelta(days=1); continue

        t = tithi_number_at(sr)

        if trad == "smartha":
            if t == 11:
                ev.append({
                    "summary": f"Ekadashi ({paksha_for_tithi(11)})",
                    "date": d,
                    "desc": f"Smārta: tithi 11 at local sunrise ({tz.zone})."
                })
        else:  # vaishnava (practical approximation)
            if t == 11:
                ev.append({
                    "summary": f"Ekadashi ({paksha_for_tithi(11)}) — Vaishnava",
                    "date": d,
                    "desc": f"Vaishnava: tithi 11 at sunrise ({tz.zone})."
                })
            else:
                # If 11 prevails at next sunrise, shift to D+1
                try:
                    sr_next = local_sun_times(lat, lon, d + timedelta(days=1), tz)[0]
                except Exception:
                    d += timedelta(days=1); continue
                if tithi_number_at(sr_next) == 11:
                    ev.append({
                        "summary": f"Ekadashi ({paksha_for_tithi(11)}) — Vaishnava",
                        "date": d + timedelta(days=1),
                        "desc": f"Vaishnava shift: Ekadashi at next sunrise ({tz.zone})."
                    })
        d += timedelta(days=1)

    # Add approximate name label by month/paksha (lightweight version)
    _label_ekadashi_names(ev)
    return _dedup(ev)

# A light, practical labeler: names by rough Gregorian month + paksha.
# (Note: true lunar-month names need amanta/purnimanta & sun in rashi; we’ll refine later.)
_EKADASHI_NAME_MAP = {
    ("Shukla", 1): "Putrada",   ("Krishna", 1): "Saphala",
    ("Shukla", 2): "Shattila",  ("Krishna", 2): "Apara",
    ("Shukla", 3): "Jaya",      ("Krishna", 3): "Vijaya",
    ("Shukla", 4): "Amalaki",   ("Krishna", 4): "Papamochani",
    ("Shukla", 5): "Kamada",    ("Krishna", 5): "Varuthini",
    ("Shukla", 6): "Mohini",    ("Krishna", 6): "Apara/Āchala",
    ("Shukla", 7): "Nirjala",   ("Krishna", 7): "Yogini",
    ("Shukla", 8): "Padma/Devshayani", ("Krishna", 8): "Kamika",
    ("Shukla", 9): "Pavitra",   ("Krishna", 9): "Aja",
    ("Shukla",10): "Parivartini/Padma", ("Krishna",10): "Indira",
    ("Shukla",11): "Papankusha", ("Krishna",11): "Rama",
    ("Shukla",12): "Prabodhini/Devutthana", ("Krishna",12): "Utpanna",
}

def _label_ekadashi_names(events: List[Dict]):
    for e in events:
        # month approx = Gregorian month of the event date
        m = e["date"].month
        pak = "Shukla" if "Shukla" in e["summary"] else "Krishna"
        name = _EKADASHI_NAME_MAP.get((pak, m))
        if name:
            e["summary"] = f"{name} Ekadashi ({pak})"

# ======== Sankashti Chaturthi (moonrise, Krishna paksha) ========
def sankashti_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year, 1, 1); end = date(year, 12, 31)
    ev: List[Dict] = []
    while d <= end:
        mr = local_moonrise(lat, lon, d, tz)
        if mr is not None:
            t = tithi_number_at(mr)
            if t == 4 and paksha_for_tithi(t) == "Krishna":
                ev.append({
                    "summary": "Sankashti Chaturthi (Krishna)",
                    "date": d,
                    "desc": f"Tithi 4 at local moonrise ({tz.zone})."
                })
        else:
            # fallback at high latitudes
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                t = tithi_number_at(sr)
                if t == 4 and paksha_for_tithi(t) == "Krishna":
                    ev.append({
                        "summary": "Sankashti Chaturthi (Krishna) — approx",
                        "date": d,
                        "desc": f"No moonrise; used sunrise tithi ({tz.zone})."
                    })
            except Exception:
                pass
        d += timedelta(days=1)
    return ev

# ======== Amavasya / Purnima (sunrise) ========
def amavasya_purnima_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year, 1, 1); end = date(year, 12, 31)
    ev: List[Dict] = []
    while d <= end:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
        except Exception:
            d += timedelta(days=1); continue
        t = tithi_number_at(sr)
        if t == 30:
            ev.append({"summary": "Amavasya", "date": d, "desc": f"Tithi 30 at sunrise ({tz.zone})."})
        elif t == 15:
            ev.append({"summary": "Purnima", "date": d, "desc": f"Tithi 15 at sunrise ({tz.zone})."})
        d += timedelta(days=1)
    return ev

# ======== Rahu Kaal (timed, daily) ========
def rahu_kaal_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year, 1, 1); end = date(year, 12, 31)
    ev: List[Dict] = []
    while d <= end:
        try:
            start, endt = rahu_kaal_for_day(lat, lon, d, tz)
            ev.append({
                "summary": "Rahu Kaal",
                "date_start": start,
                "date_end": endt,
                "all_day": False,
                "desc": f"Based on daytime eighths ({tz.zone})."
            })
        except Exception:
            pass
        d += timedelta(days=1)
    return ev

# ======== Orchestrator ========
def events_for_year(
    lat: float, lon: float, year: int, *,
    tradition: str = "smartha",
    include_sankashti: bool = True,
    include_amavasya_purnima: bool = True,
    include_rahukaal: bool = True,
) -> List[Dict]:
    ev: List[Dict] = []
    # All-day first:
    ev += ekadashi_events_for_year(lat, lon, year, tradition=tradition)
    if include_sankashti:
        ev += sankashti_events_for_year(lat, lon, year)
    if include_amavasya_purnima:
        ev += amavasya_purnima_events_for_year(lat, lon, year)
    # Timed next:
    if include_rahukaal:
        ev += rahu_kaal_events_for_year(lat, lon, year)
    # Sort: timed events (with 'date_start') get sorted by start, all-day by date
    def _key(e):
        if e.get("all_day", True):
            return (e["date"], datetime.min.time())
        return (e["date_start"].date(), e["date_start"].time())
    ev.sort(key=_key)
    return ev

def _dedup(events: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for e in events:
        key = (e["summary"], e.get("date") or e.get("date_start"))
        if key not in seen:
            seen.add(key); out.append(e)
    return out
