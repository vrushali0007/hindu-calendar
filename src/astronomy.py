# src/astronomy.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import floor
from typing import List, Dict, Tuple, Optional, NamedTuple

import pytz
from timezonefinder import TimezoneFinder
from astral import LocationInfo
from astral.sun import sun
from astral.moon import moonrise
from skyfield.api import load

# -------------------------
# Ephemerides (Skyfield)
# -------------------------
_eph = None
_ts = None
def _load_ephem():
    global _eph, _ts
    if _eph is None or _ts is None:
        _eph = load("de421.bsp")
        _ts = load.timescale()
    return _eph, _ts

# -------------------------
# Timezone & local rise/set
# -------------------------
def iana_timezone_for(lat: float, lon: float):
    tzname = TimezoneFinder().timezone_at(lng=lon, lat=lat) or "UTC"
    return pytz.timezone(tzname)

def local_sun_times(lat: float, lon: float, day: date, tz) -> Tuple[datetime, datetime]:
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz.zone)
    sdict = sun(loc.observer, date=day, tzinfo=tz)
    return sdict["sunrise"], sdict["sunset"]

def local_moonrise(lat: float, lon: float, day: date, tz) -> Optional[datetime]:
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz.zone)
    try:
        return moonrise(loc.observer, date=day, tzinfo=tz)
    except Exception:
        return None

# -------------------------
# Ecliptic longitudes & tithi
# -------------------------
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

def tithi_abs(paksha: str, ordinal: int) -> int:
    """Convert (paksha, 1..15) → absolute tithi 1..30. Example: Krishna Chaturthi → 19."""
    return ordinal if paksha.lower() == "shukla" else 15 + ordinal

# -------------------------
# Sidereal Sun (approx Lahiri) for month naming
# -------------------------
def _julian_centuries_tt(dt_aware: datetime) -> float:
    dt_utc = dt_aware.astimezone(timezone.utc)
    y, m = dt_utc.year, dt_utc.month
    d = dt_utc.day + (dt_utc.hour + (dt_utc.minute + dt_utc.second/60)/60)/24
    if m <= 2:
        y -= 1; m += 12
    A = floor(y/100); B = 2 - A + floor(A/4)
    JD = floor(365.25*(y+4716)) + floor(30.6001*(m+1)) + d + B - 1524.5
    return (JD - 2451545.0) / 36525.0

def lahiri_ayanamsha_deg(dt_aware: datetime) -> float:
    T = _julian_centuries_tt(dt_aware)
    lahiri_2000_sec = 23*3600 + 51*60  # 85,860"
    precession_sec = 5028.796195 * T   # rough; good enough for naming
    return (lahiri_2000_sec - precession_sec) / 3600.0

def sun_sidereal_longitude(dt_aware: datetime) -> float:
    lon_sun, _ = _ecliptic_longitudes(dt_aware)
    ay = lahiri_ayanamsha_deg(dt_aware)
    return (lon_sun - ay) % 360.0

# -------------------------
# Rahu Kaal (daylight eighths)
# -------------------------
# Mon..Sun → segment 1..8 (index from weekday())
_RAHU_SEG = { 0:2, 1:7, 2:5, 3:6, 4:4, 5:3, 6:8 }

def rahu_kaal_for_day(lat: float, lon: float, day: date, tz) -> Tuple[datetime, datetime]:
    """Robust even at DST/polar edges: always returns a positive daylight slot."""
    sr, ss = local_sun_times(lat, lon, day, tz)
    if ss <= sr:
        ss = sr + timedelta(hours=12)
    span = (ss - sr).total_seconds() or 12*3600
    seg_len = span / 8.0
    seg = _RAHU_SEG[day.weekday()]
    start = sr + timedelta(seconds=(seg-1)*seg_len)
    end   = start + timedelta(seconds=seg_len)
    return start, end

# -------------------------
# New moon finder (UTC)
# -------------------------
@dataclass
class Lunation:
    amavasya: datetime  # exact UTC instant

def _find_amavasya_utc(dt_guess_utc: datetime) -> Optional[datetime]:
    def wrap180(x): return (x + 180.0) % 360.0 - 180.0
    def f(dt):
        ls, lm = _ecliptic_longitudes(dt.replace(tzinfo=timezone.utc))
        return wrap180(lm - ls)

    left  = dt_guess_utc - timedelta(hours=36)
    right = dt_guess_utc + timedelta(hours=36)

    fl, fr = f(left), f(right)
    tries = 0
    while fl * fr > 0 and tries < 6:
        left  -= timedelta(hours=24)
        right += timedelta(hours=24)
        fl, fr = f(left), f(right)
        tries += 1
    if fl * fr > 0:
        return None

    for _ in range(50):
        mid = left + (right - left) / 2
        fm = f(mid)
        if abs(fm) < 1e-4:
            return mid.replace(tzinfo=timezone.utc)
        if fl * fm <= 0:
            right, fr = mid, fm
        else:
            left,  fl = mid, fm
    return (left + (right - left) / 2).replace(tzinfo=timezone.utc)

def lunations_covering_year(year: int) -> List[Lunation]:
    start = datetime(year-1, 12, 10, tzinfo=timezone.utc)
    end   = datetime(year+1,  1, 20, tzinfo=timezone.utc)
    guesses, cur = [], start
    while cur <= end:
        guesses.append(cur); cur += timedelta(days=29, hours=13)
    found: List[datetime] = []
    for g in guesses:
        av = _find_amavasya_utc(g)
        if av is None: continue
        if any(abs((av - x).total_seconds()) < 18*3600 for x in found): continue
        found.append(av)
    found.sort()
    return [Lunation(amavasya=x) for x in found]

# -------------------------
# Amānta month naming (sidereal Sun at Amavasya)
# -------------------------
AMANTA_MONTHS = [
    "Chaitra","Vaisakha","Jyeshtha","Ashadha","Shravana","Bhadrapada",
    "Ashwin","Kartika","Margashirsha","Pausha","Magha","Phalguna"
]

def _amanta_index_from_sidereal(lam_sun_sid_deg: float) -> int:
    # 0..11, 0=Chaitra (sidereal Aries near Chaitra new moon)
    return int(floor(((lam_sun_sid_deg + 30.0) % 360.0) / 30.0))

class LunationInterval(NamedTuple):
    start_utc: datetime
    end_utc: datetime
    name: str  # amānta month name

def amanta_lunation_intervals(year: int) -> List[LunationInterval]:
    lun = lunations_covering_year(year)
    intervals: List[LunationInterval] = []
    for i in range(len(lun) - 1):
        av = lun[i].amavasya
        nxt = lun[i+1].amavasya
        lam_sid = sun_sidereal_longitude(av)
        idx = _amanta_index_from_sidereal(lam_sid)
        intervals.append(LunationInterval(av, nxt, AMANTA_MONTHS[idx]))
    return intervals

# -------------------------
# All-day observances
# -------------------------
def ekadashi_events_for_year(lat: float, lon: float, year: int, tradition: str = "smartha") -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year,1,1); end = date(year,12,31)
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
                ev.append({"summary": f"Ekadashi ({paksha_for_tithi(11)})", "date": d,
                           "desc": f"Smārta: tithi 11 at sunrise ({tz.zone})."})
        else:  # vaishnava shift if needed
            if t == 11:
                ev.append({"summary": f"Ekadashi ({paksha_for_tithi(11)}) — Vaishnava", "date": d,
                           "desc": f"Vaishnava: tithi 11 at sunrise ({tz.zone})."})
            else:
                try:
                    sr_next = local_sun_times(lat, lon, d + timedelta(days=1), tz)[0]
                    if tithi_number_at(sr_next) == 11:
                        ev.append({"summary": f"Ekadashi ({paksha_for_tithi(11)}) — Vaishnava", "date": d + timedelta(days=1),
                                   "desc": f"Vaishnava shift: Ekadashi at next sunrise ({tz.zone})."})
                except Exception:
                    pass
        d += timedelta(days=1)

    _label_ekadashi_names(ev)
    return _dedup(ev)

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
        m = e["date"].month
        pak = "Shukla" if "Shukla" in e["summary"] else "Krishna"
        nm = _EKADASHI_NAME_MAP.get((pak, m))
        if nm:
            e["summary"] = f"{nm} Ekadashi ({pak})"

# -------------------------
# Sankashti Chaturthi (Krishna Chaturthi per lunation)
# -------------------------
def sankashti_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    intervals = amanta_lunation_intervals(year)
    out: List[Dict] = []

    for iv in intervals:
        start_local = iv.start_utc.astimezone(tz).date()
        end_local   = (iv.end_utc - timedelta(seconds=1)).astimezone(tz).date()
        pick: Optional[date] = None

        # Prefer moonrise-based match
        d = start_local
        while d <= end_local:
            mr = local_moonrise(lat, lon, d, tz)
            if mr:
                t = tithi_number_at(mr)
                if t == tithi_abs("Krishna", 4):  # 19
                    pick = d; break
            d += timedelta(days=1)

        # Fallback: hourly scan for first Krishna Chaturthi date
        if pick is None:
            d = start_local
            found = False
            while d <= end_local and not found:
                for hh in range(0, 24):
                    try:
                        chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                        t = tithi_number_at(chk)
                        if t == tithi_abs("Krishna", 4):  # 19
                            pick = d; found = True; break
                    except Exception:
                        pass
                d += timedelta(days=1)

        if pick is not None:
            mr = local_moonrise(lat, lon, pick, tz)
            desc = (f"Krishna Chaturthi (tithi 19) at moonrise ({tz.zone})."
                    if (mr and tithi_number_at(mr) == tithi_abs("Krishna", 4))
                    else f"Krishna Chaturthi detected during day (no/unsuitable moonrise) ({tz.zone}).")
            out.append({"summary":"Sankashti Chaturthi (Krishna)", "date": pick, "desc": desc})

    out.sort(key=lambda e: e["date"])
    return out

# -------------------------
# Amavasya / Purnima
# -------------------------
def amavasya_purnima_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year,1,1); end = date(year,12,31)
    out: List[Dict] = []
    while d <= end:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            t = tithi_number_at(sr)
            if t == 30:
                out.append({"summary":"Amavasya","date": d,"desc": f"Tithi 30 at sunrise ({tz.zone})."})
            elif t == 15:
                out.append({"summary":"Purnima","date": d,"desc": f"Tithi 15 at sunrise ({tz.zone})."})
        except Exception:
            pass
        d += timedelta(days=1)
    return out

# -------------------------
# Rahu Kaal (timed events)
# -------------------------
def rahu_kaal_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year, 1, 1); end = date(year, 12, 31)
    out: List[Dict] = []
    while d <= end:
        try:
            st, en = rahu_kaal_for_day(lat, lon, d, tz)
            out.append({"summary":"Rahu Kaal","date_start": st,"date_end": en,"all_day": False,
                        "desc": f"Day divided into eight parts; weekday segment ({tz.zone})."})
        except Exception:
            pass
        d += timedelta(days=1)
    out.sort(key=lambda e: (e["date_start"].date(), e["date_start"].time()))
    return out

# -------------------------
# Festivals (computed within lunation intervals)
# -------------------------
def _local_range_from_interval(tz, iv: LunationInterval) -> Tuple[date, date]:
    start_local = iv.start_utc.astimezone(tz).date()
    end_local   = (iv.end_utc - timedelta(seconds=1)).astimezone(tz).date()
    return start_local, end_local

def rule_gudi_padwa(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Chaitra": continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                if tithi_number_at(sr) == 1:
                    out.append({"summary":"Gudi Padwa (Maharashtra New Year)","date": d,
                                "desc": f"Chaitra Shukla Pratipada at sunrise ({tz.zone})."})
                    return out
            except Exception: pass
            d += timedelta(days=1)
    return out

def rule_ganesh_chaturthi(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Bhadrapada": continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                t = tithi_number_at(sr)
                if t == 4 and paksha_for_tithi(t) == "Shukla":
                    out.append({"summary":"Ganesh Chaturthi / Vinayaka Chaturthi","date": d,
                                "desc": f"Bhadrapada Shukla Chaturthi at sunrise ({tz.zone})."})
                    return out
            except Exception: pass
            d += timedelta(days=1)
    return out

def rule_navaratri_start(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Ashwin": continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                if tithi_number_at(sr) == 1:
                    out.append({"summary":"Shardiya Navaratri begins","date": d,
                                "desc": f"Ashwin Shukla Pratipada at sunrise ({tz.zone})."})
                    return out
            except Exception: pass
            d += timedelta(days=1)
    return out

def rule_diwali(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Kartika": continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                if tithi_number_at(sr) == 30:
                    out.append({"summary":"Diwali / Deepavali","date": d,
                                "desc": f"Kartika Amavasya (tithi 30 at sunrise, {tz.zone})."})
                    return out
            except Exception: pass
            d += timedelta(days=1)
    return out

def rule_karwa_chauth(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    """
    Karwa Chauth is Purnimānta Kartika Krishna Chaturthi (moonrise).
    In Amānta labeling that falls inside **Ashwin** (Krishna paksha).
    """
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Ashwin":
            continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            mr = local_moonrise(lat, lon, d, tz)
            if mr:
                t = tithi_number_at(mr)
                if t == tithi_abs("Krishna", 4):  # 19
                    out.append({"summary":"Karwa Chauth","date": d,
                                "desc": f"Krishna Chaturthi (tithi 19) at moonrise ({tz.zone})."})
                    return out
            # fallback: evening scan if no moonrise reported
            for hh in range(15, 24):
                try:
                    chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                    t = tithi_number_at(chk)
                    if t == tithi_abs("Krishna", 4):
                        out.append({"summary":"Karwa Chauth","date": d,
                                    "desc": f"Krishna Chaturthi detected in evening ({chk.strftime('%H:%M %Z')})."})
                        return out
                except Exception:
                    pass
            d += timedelta(days=1)
    return out

def rule_mahashivratri(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Phalguna": continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            try:
                night = tz.localize(datetime(d.year, d.month, d.day, 20, 0))
                if tithi_number_at(night) == 29 and paksha_for_tithi(29) == "Krishna":
                    out.append({"summary":"Mahashivratri","date": d,
                                "desc": f"Phalguna Krishna Chaturdashi (night), {tz.zone}."})
                    return out
            except Exception: pass
            d += timedelta(days=1)
    return out

def rule_guru_nanak_jayanti(lat, lon, year, tz, intervals: List[LunationInterval]) -> List[Dict]:
    out: List[Dict] = []
    for iv in intervals:
        if iv.name != "Kartika": continue
        d0, d1 = _local_range_from_interval(tz, iv)
        d = d0
        while d <= d1:
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                if tithi_number_at(sr) == 15:
                    out.append({"summary":"Guru Nanak Jayanti","date": d,
                                "desc": f"Kartika Purnima at sunrise ({tz.zone})."})
                    return out
            except Exception: pass
            d += timedelta(days=1)
    return out

FESTIVALS = [
    {"key":"diwali",           "rule": rule_diwali},
    {"key":"karwa_chauth",     "rule": rule_karwa_chauth},
    {"key":"mahashivratri",    "rule": rule_mahashivratri},
    {"key":"gudi_padwa",       "rule": rule_gudi_padwa},
    {"key":"ganesh_chaturthi", "rule": rule_ganesh_chaturthi},
    {"key":"navaratri_start",  "rule": rule_navaratri_start},
    {"key":"guru_nanak",       "rule": rule_guru_nanak_jayanti},
]

def festivals_for_year(lat: float, lon: float, year: int, which: Optional[str] = "all") -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    intervals = amanta_lunation_intervals(year)
    chosen = FESTIVALS if which in (None,"all") else [f for f in FESTIVALS if f["key"] in which.split(",")]
    out: List[Dict] = []
    for f in chosen:
        out += f["rule"](lat, lon, year, tz, intervals)
    return out

# -------------------------
# Orchestrator
# -------------------------
def events_for_year(
    lat: float, lon: float, year: int, *,
    tradition: str = "smartha",
    include_sankashti: bool = True,
    include_amavasya_purnima: bool = True,
    include_rahukaal: bool = True,
    include_festivals: bool = True,
    festivals_which: Optional[str] = "all",
) -> List[Dict]:
    ev: List[Dict] = []
    ev += ekadashi_events_for_year(lat, lon, year, tradition=tradition)
    if include_sankashti:
        ev += sankashti_events_for_year(lat, lon, year)
    if include_amavasya_purnima:
        ev += amavasya_purnima_events_for_year(lat, lon, year)
    if include_festivals:
        ev += festivals_for_year(lat, lon, year, which=festivals_which)
    if include_rahukaal:
        ev += rahu_kaal_events_for_year(lat, lon, year)

    def _key(e):
        if e.get("all_day", True):
            return (e["date"], time(0,0))
        return (e["date_start"].date(), e["date_start"].time())
    ev.sort(key=_key)
    return _dedup(ev)

def _dedup(events: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for e in events:
        key = (e["summary"], e.get("date") or (e.get("date_start") and e["date_start"].date()))
        if key not in seen:
            seen.add(key); out.append(e)
    return out