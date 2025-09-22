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

# ---------------- Ephemerides ----------------
_eph = None
_ts = None
def _load_ephem():
    global _eph, _ts
    if _eph is None or _ts is None:
        _eph = load("de421.bsp")
        _ts = load.timescale()
    return _eph, _ts

# --------------- Timezone & Rise/Set ----------
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

# ---------------- Tithi math -------------------
def _ts_from_dt(dt_aware: datetime):
    eph, ts = _load_ephem()
    dt_utc = dt_aware.astimezone(pytz.utc)
    sec = dt_utc.second + dt_utc.microsecond / 1e6
    t = ts.utc(dt_utc.year, dt_utc.month, dt_utc.day,
               dt_utc.hour, dt_utc.minute, sec)
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
    return ordinal if paksha.lower() == "shukla" else 15 + ordinal

# ------------- Sidereal Sun (Lahiri) ----------
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
    lahiri_2000_sec = 23*3600 + 51*60
    precession_sec = 5028.796195 * T
    return (lahiri_2000_sec - precession_sec) / 3600.0

def sun_sidereal_longitude(dt_aware: datetime) -> float:
    lon_sun, _ = _ecliptic_longitudes(dt_aware)
    ay = lahiri_ayanamsha_deg(dt_aware)
    return (lon_sun - ay) % 360.0

def sidereal_solar_month_index(dt_aware: datetime) -> int:
    return int(floor(sun_sidereal_longitude(dt_aware) / 30.0)) % 12

# ---------------- Rahu Kaal --------------------
_RAHU_SEG = { 0:2, 1:7, 2:5, 3:6, 4:4, 5:3, 6:8 }  # Mon..Sun

def rahu_kaal_for_day(lat: float, lon: float, day: date, tz) -> Tuple[datetime, datetime]:
    sr, ss = local_sun_times(lat, lon, day, tz)
    if ss <= sr:  # DST/polar guard
        ss = sr + timedelta(hours=12)
    span = max(1, (ss - sr).total_seconds())
    seg_len = span / 8.0
    seg = _RAHU_SEG[day.weekday()]
    start = sr + timedelta(seconds=(seg-1)*seg_len)
    end   = start + timedelta(seconds=seg_len)
    return start, end

# ------------- New moon / lunations -------------
@dataclass
class Lunation:
    amavasya: datetime  # UTC

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
    cur = start
    guesses = []
    while cur <= end:
        guesses.append(cur)
        cur += timedelta(days=29, hours=13)
    found: List[datetime] = []
    for g in guesses:
        av = _find_amavasya_utc(g)
        if av is None:
            continue
        if any(abs((av - x).total_seconds()) < 18*3600 for x in found):
            continue
        found.append(av)
    found.sort()
    return [Lunation(x) for x in found]

class LunationInterval(NamedTuple):
    start_utc: datetime
    end_utc: datetime

def amanta_lunation_intervals(year: int) -> List[LunationInterval]:
    lun = lunations_covering_year(year)
    return [LunationInterval(lun[i].amavasya, lun[i+1].amavasya)
            for i in range(len(lun)-1)]

def _local_range_from_interval(tz, iv: LunationInterval) -> Tuple[date, date]:
    start_local = iv.start_utc.astimezone(tz).date()
    end_local   = (iv.end_utc - timedelta(seconds=1)).astimezone(tz).date()
    return start_local, end_local

def _tithi_at_sunrise(lat, lon, d: date, tz) -> Optional[int]:
    try:
        sr = local_sun_times(lat, lon, d, tz)[0]
        return tithi_number_at(sr)
    except Exception:
        return None

def _first_sunrise_tithi_date_in_interval(lat, lon, tz, iv: LunationInterval, abs_tithi: int) -> Optional[date]:
    d0, d1 = _local_range_from_interval(tz, iv)
    d = d0
    while d <= d1:
        if _tithi_at_sunrise(lat, lon, d, tz) == abs_tithi:
            return d
        d += timedelta(days=1)
    return None

def _first_anytime_tithi_date_in_interval(lat, lon, tz, iv: LunationInterval, abs_tithi: int) -> Optional[date]:
    d0, d1 = _local_range_from_interval(tz, iv)
    d = d0
    while d <= d1:
        for hh in range(0, 24):
            try:
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == abs_tithi:
                    return d
            except Exception:
                pass
        d += timedelta(days=1)
    return None

def _collect_sunrise_tithi_dates_in_interval(lat, lon, tz, iv: LunationInterval, abs_tithi_set: set[int]) -> Dict[int, date]:
    out: Dict[int, date] = {}
    d0, d1 = _local_range_from_interval(tz, iv)
    d = d0
    need = set(abs_tithi_set)
    while d <= d1 and need:
        t = _tithi_at_sunrise(lat, lon, d, tz)
        if t in need:
            out[t] = d
            need.remove(t)
        d += timedelta(days=1)
    return out

# --------------- Ekadashi ----------------------
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
            e["summary"] = f"{nm} Ekadashi — {pak}"

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
                ev.append({"summary": f"Ekadashi — {paksha_for_tithi(11)}", "date": d,
                           "desc": f"Smārta (tithi 11 at sunrise, {tz.zone})."})
        else:
            if t == 11:
                ev.append({"summary": f"Ekadashi — {paksha_for_tithi(11)} (Vaishnava)", "date": d,
                           "desc": f"Vaishnava at sunrise ({tz.zone})."})
            else:
                try:
                    sr_next = local_sun_times(lat, lon, d + timedelta(days=1), tz)[0]
                    if tithi_number_at(sr_next) == 11:
                        ev.append({"summary": f"Ekadashi — {paksha_for_tithi(11)} (Vaishnava)",
                                   "date": d + timedelta(days=1),
                                   "desc": f"Vaishnava shift: next sunrise ({tz.zone})."})
                except Exception:
                    pass
        d += timedelta(days=1)

    _label_ekadashi_names(ev)
    return _dedup(ev)

# --------------- Sankashti (moonrise) ----------
def sankashti_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    intervals = amanta_lunation_intervals(year)
    out: List[Dict] = []
    for iv in intervals:
        d0, d1 = _local_range_from_interval(tz, iv)
        pick: Optional[date] = None
        d = d0
        while d <= d1 and pick is None:
            mr = local_moonrise(lat, lon, d, tz)
            if mr and tithi_number_at(mr) == tithi_abs("Krishna", 4):
                pick = d; break
            # evening fallback
            for hh in range(12, 24):
                try:
                    chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                    if tithi_number_at(chk) == tithi_abs("Krishna", 4):
                        pick = d; break
                except Exception:
                    pass
            d += timedelta(days=1)
        if pick:
            out.append({"summary":"Sankashti Chaturthi (Krishna)", "date": pick,
                        "desc": f"Krishna Chaturthi per lunation ({tz.zone})."})
    out.sort(key=lambda e: e["date"])
    return out

# --------------- Amavasya / Purnima -------------
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

# --------------- Rahu Kaal (timed) --------------
def rahu_kaal_events_for_year(lat: float, lon: float, year: int) -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    d = date(year, 1, 1); end = date(year, 12, 31)
    per_day: Dict[date, List[Tuple[datetime, datetime]]] = {}
    while d <= end:
        try:
            st, en = rahu_kaal_for_day(lat, lon, d, tz)
            per_day.setdefault(d, []).append((st, en))
        except Exception:
            pass
        d += timedelta(days=1)
    out: List[Dict] = []
    for day, slots in per_day.items():
        st, en = sorted(slots, key=lambda p: p[0])[-1]   # latest start only
        out.append({"summary":"Rahu Kaal","date_start": st,"date_end": en,"all_day": False,
                    "desc": f"Day split in eight; weekday segment ({tz.zone})."})
    out.sort(key=lambda e: (e["date_start"].date(), e["date_start"].time()))
    return out

# --------------- Festival rules -----------------


def _at_local_time(tz, d: date, hh: int, mm: int = 0) -> datetime:
    """Localize a naive datetime to the given tz safely."""
    return tz.localize(datetime(d.year, d.month, d.day, hh, mm))


# ---- Build daily amānta month map for the whole year ----
AMANTA_MONTHS = ["Chaitra","Vaisakha","Jyeshtha","Ashadha","Shravana","Bhadrapada",
                 "Ashwin","Kartika","Margashirsha","Pausha","Magha","Phalguna"]

def _amanta_index_from_sidereal(lam_sun_sid_deg: float) -> int:
    # 0..11, 0 => Chaitra (sidereal Aries maps to Chaitra after a +30° shift)
    return int(floor(((sun_sidereal_longitude(datetime(2000,1,1, tzinfo=timezone.utc))  # dummy call, ignored
                       # NOTE: we only need the formula; ignore the value above.
                      ) + 30.0) % 360.0 / 30.0))  # kept to remind shift; real value set below

def amanta_month_map_for_year(lat: float, lon: float, year: int) -> Dict[date, str]:
    """
    Map each civil date in the given year -> amānta lunar month name.
    We use UTC lunations and label each interval by sidereal Sun longitude at Amavasya.
    """
    lun = lunations_covering_year(year)
    if not lun:
        # fallback: bland map to Chaitra; avoids crashes
        return {date(year,1,1) + timedelta(days=k): AMANTA_MONTHS[0]
                for k in range(366) if (date(year,1,1) + timedelta(days=k)).year == year}

    # Build (start,end,name) intervals
    intervals: List[Tuple[datetime, datetime, str]] = []
    for i in range(len(lun) - 1):
        av = lun[i].amavasya
        nxt = lun[i+1].amavasya
        lam_sid = sun_sidereal_longitude(av)
        # Aries(0°) is Chaitra, but amānta months are named by the Sun's sidereal sign at/after Amavasya.
        idx = int(floor(((lam_sid + 30.0) % 360.0) / 30.0))  # 0..11
        intervals.append((av, nxt, AMANTA_MONTHS[idx]))

    out: Dict[date, str] = {}
    tz_utc = timezone.utc
    d = date(year, 1, 1); end = date(year, 12, 31)
    while d <= end:
        probe = datetime(d.year, d.month, d.day, 12, 0, tzinfo=tz_utc)
        name = AMANTA_MONTHS[0]
        for a, b, nm in intervals:
            if a <= probe < b:
                name = nm
                break
        out[d] = name
        d += timedelta(days=1)
    return out


def _find_ganesh_interval_index(lat: float, lon: float, tz, intervals: List["LunationInterval"]) -> Optional[int]:
    """
    Identify which lunation likely corresponds to Bhadrapada Shukla Chaturthi.
    Tries sunrise first, then any time in interval.
    """
    target = tithi_abs("Shukla", 4)
    for i, iv in enumerate(intervals):
        d = _first_sunrise_tithi_date_in_interval(lat, lon, tz, iv, target)
        if d:
            return i
        d2 = _first_anytime_tithi_date_in_interval(lat, lon, tz, iv, target)
        if d2:
            return i
    return None
def rule_gudi_padwa(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """Gudi Padwa: Chaitra Shukla Pratipada (Mar 15 – Apr 20 window)."""
    out: List[Dict] = []
    start = date(year, 3, 15); end = date(year, 4, 20)

    d = start
    while d <= end:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            if tithi_number_at(sr) == tithi_abs("Shukla", 1):
                out.append({"summary": "Gudi Padwa (Maharashtra New Year)",
                            "date": d,
                            "desc": f"Chaitra Shukla Pratipada at sunrise ({tz.zone})."})
                break
            # hourly fallback
            for hh in range(0, 24):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 1):
                    out.append({"summary": "Gudi Padwa (Maharashtra New Year)",
                                "date": d,
                                "desc": f"Chaitra Shukla Pratipada (hour {hh:02d}), {tz.zone}."})
                    d = end
                    break
        except Exception:
            pass
        d += timedelta(days=1)

    return out



def rule_makara_sankranti(lat, lon, year, tz, intervals) -> List[Dict]:
    out: List[Dict] = []
    d = date(year,1,1); end = date(year,12,31)
    prev = sidereal_solar_month_index(tz.localize(datetime(d.year, d.month, d.day, 12)))
    while d <= end:
        chk = tz.localize(datetime(d.year, d.month, d.day, 12))
        idx = sidereal_solar_month_index(chk)
        if prev != idx and idx == 9:  # Makara
            out.append({"summary":"Makara Sankranti","date": d,
                        "desc": f"Sun enters sidereal Makara ({tz.zone})."})
            break
        prev = idx; d += timedelta(days=1)
    return out

def rule_ganesh_chaturthi(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """
    Ganesh Chaturthi / Vinayaka Chaturthi:
      - Shukla Chaturthi (tithi 4) in Aug 20 – Sep 25 local.
      - Prefer sunrise; fallback to any hour that day.
    """
    out: List[Dict] = []
    start, end = date(year, 8, 20), date(year, 9, 25)

    d = start
    while d <= end:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            if tithi_number_at(sr) == tithi_abs("Shukla", 4):
                out.append({"summary":"Ganesh Chaturthi / Vinayaka Chaturthi",
                            "date": d,
                            "desc": f"Shukla Chaturthi at sunrise ({tz.zone})."})
                break
            # hourly fallback (any time that civil day)
            for hh in range(0, 24):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 4):
                    out.append({"summary":"Ganesh Chaturthi / Vinayaka Chaturthi",
                                "date": d,
                                "desc": f"Shukla Chaturthi present (hour {hh:02d}), {tz.zone}."})
                    d = end
                    break
        except Exception:
            pass
        d += timedelta(days=1)

    return out

def rule_mahashivratri(lat: float, lon: float, year: int, tz, intervals) -> List[Dict]:
    """
    Mahashivratri: Phalguna Krishna Chaturdashi (night).
    Using the amānta month map, search dates labeled 'Phalguna' and prefer night check.
    """
    out: List[Dict] = []
    month_map = amanta_month_map_for_year(lat, lon, year)

    d = date(year, 1, 1); end = date(year, 12, 31)
    while d <= end:
        if month_map.get(d) == "Phalguna":
            try:
                night = _at_local_time(tz, d, 20, 0)
                if tithi_number_at(night) == tithi_abs("Krishna", 14):
                    out.append({
                        "summary": "Mahashivratri",
                        "date": d,
                        "desc": f"Phalguna Krishna Chaturdashi (night), {tz.zone}."
                    })
                    break
            except Exception:
                pass
        d += timedelta(days=1)
    return out

def rule_hartalika_teej(lat, lon, year, tz, intervals) -> List[Dict]:
    """
    Hartalika Teej: Shukla Tritiya, ideally the day before Ganesh Chaturthi.
    Fallback: first Tritiya in Aug 20 – Sep 25.
    """
    out: List[Dict] = []
    # Find Ganesh first (using the seasonal rule above)
    g = rule_ganesh_chaturthi(lat, lon, year, tz, intervals)
    ganesh = g[0]["date"] if g else None

    # Try Ganesh - 1 day
    def is_tritiya(d: date) -> bool:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            if tithi_number_at(sr) == tithi_abs("Shukla", 3):
                return True
            for hh in range(0, 24):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 3):
                    return True
        except Exception:
            pass
        return False

    if ganesh:
        cand = ganesh - timedelta(days=1)
        if is_tritiya(cand):
            out.append({"summary":"Hartalika Teej",
                        "date": cand,
                        "desc": f"Day before Ganesh; Shukla Tritiya verified ({tz.zone})."})
            return out

    # Fallback scan
    start, end = date(year, 8, 20), date(year, 9, 25)
    d = start
    while d <= end:
        if is_tritiya(d):
            out.append({"summary":"Hartalika Teej",
                        "date": d,
                        "desc": f"Shukla Tritiya (seasonal window) ({tz.zone})."})
            break
        d += timedelta(days=1)
    return out
def rule_hariyali_teej(lat, lon, year, tz, intervals) -> List[Dict]:
    out: List[Dict] = []
    gi = _find_ganesh_interval_index(lat, lon, tz, intervals)
    if gi is None or gi == 0: return out
    iv_prev = intervals[gi-1]
    d = _first_sunrise_tithi_date_in_interval(lat, lon, tz, iv_prev, tithi_abs("Shukla", 3)) \
        or _first_anytime_tithi_date_in_interval(lat, lon, tz, iv_prev, tithi_abs("Shukla", 3))
    if d:
        out.append({"summary":"Hariyali Teej","date": d,
                    "desc": f"Shukla Tritiya (pre-Ganesh lunation) ({tz.zone})."})
    return out

def rule_nag_panchami(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """Find Shukla Panchami between Jul 1 and Aug 31 (local)."""
    out: List[Dict] = []
    start = date(year, 7, 1); end = date(year, 8, 31)
    d = start
    while d <= end:
        try:
            sr = local_sun_times(lat, lon, d, tz)[0]
            if tithi_number_at(sr) == tithi_abs("Shukla", 5):
                out.append({"summary":"Nag Panchami","date": d,
                            "desc": f"Shravana Shukla Panchami (sunrise), {tz.zone}."})
                return out
            for hh in range(0, 24):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 5):
                    out.append({"summary":"Nag Panchami","date": d,
                                "desc": f"Shravana Shukla Panchami (hour {hh:02d}), {tz.zone}."})
                    return out
        except Exception:
            pass
        d += timedelta(days=1)
    return out

def rule_navaratri_set(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """
    Find the Amavasya (t=30 at sunrise) in Sep–Oct that ends Pitru Paksha,
    then take Shukla 1/8/9/10 afterward for Navratri cluster.
    """
    out: List[Dict] = []

    # 1) Find the Sep–Oct Amavasya that ends Pitru Paksha
    amav = None
    d = date(year, 9, 1); end = date(year, 10, 31)
    while d <= end:
        try:
            sr = local_sun_times(lat, lon, d, tz)[0]
            if tithi_number_at(sr) == tithi_abs("Krishna", 15):  # 30th tithi at sunrise
                amav = d
                break
        except Exception:
            pass
        d += timedelta(days=1)
    if not amav:
        return out

    # 2) From the next day, pick Shukla 1/8/9/10 within ~15 days
    need = {tithi_abs("Shukla", 1): "Shardiya Navaratri begins",
            tithi_abs("Shukla", 8): "Durga Ashtami",
            tithi_abs("Shukla", 9): "Maha Navami",
            tithi_abs("Shukla",10): "Vijayadashami / Dussehra"}

    d = amav + timedelta(days=1)
    limit = d + timedelta(days=15)
    seen: set[int] = set()

    while d <= limit and len(seen) < 4:
        try:
            sr = local_sun_times(lat, lon, d, tz)[0]
            t = tithi_number_at(sr)
            if t in need and t not in seen:
                out.append({"summary": need[t], "date": d,
                            "desc": f"Tithi at sunrise = {t} ({tz.zone})."})
                seen.add(t)
            else:
                # hourly fallback
                for hh in range(0, 24):
                    chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                    t2 = tithi_number_at(chk)
                    if t2 in need and t2 not in seen:
                        out.append({"summary": need[t2], "date": d,
                                    "desc": f"Tithi at {hh:02d}:00 = {t2} ({tz.zone})."})
                        seen.add(t2)
                        break
        except Exception:
            pass
        d += timedelta(days=1)

    out.sort(key=lambda e: e["date"])
    return out

def rule_pitru_paksha(lat, lon, year, tz, intervals) -> List[Dict]:
    """
    Pitru Paksha = from Bhadrapada Krishna Pratipada (tithi 16) 
    until Bhadrapada Amavasya (tithi 30).
    """
    out: List[Dict] = []
    # Step 1: Identify Bhadrapada Purnima → day after is Krishna 1
    # We'll find first Krishna tithi after ~Aug 15 to ~Sep 30
    start, end = date(year, 8, 15), date(year, 10, 15)
    start_date, end_date = None, None

    d = start
    while d <= end:
        try:
            sr = local_sun_times(lat, lon, d, tz)[0]
            t = tithi_number_at(sr)
            if t == tithi_abs("Krishna", 1):
                start_date = d
                break
        except Exception:
            pass
        d += timedelta(days=1)

    # Step 2: Find the next Amavasya (tithi 30 at sunrise)
    if start_date:
        d = start_date
        while d <= end:
            try:
                sr = local_sun_times(lat, lon, d, tz)[0]
                if tithi_number_at(sr) == tithi_abs("Krishna", 15):
                    end_date = d
                    break
            except Exception:
                pass
            d += timedelta(days=1)

    # Step 3: Output events
    if start_date:
        out.append({"summary":"Pitru Paksha begins","date": start_date,
                    "desc": f"Krishna Pratipada (start), {tz.zone}."})
    if end_date:
        out.append({"summary":"Pitru Paksha ends (Mahalaya Amavasya)","date": end_date,
                    "desc": f"Krishna Amavasya (end), {tz.zone}."})

    return out

def rule_karwa_chauth(lat, lon, year, tz, intervals) -> List[Dict]:
    out: List[Dict] = []
    d = date(year,9,15); end = date(year,11,15)
    while d <= end:
        mr = local_moonrise(lat, lon, d, tz)
        if mr and tithi_number_at(mr) == tithi_abs("Krishna", 4):
            out.append({"summary":"Karwa Chauth","date": d,
                        "desc": f"Krishna Chaturthi at moonrise ({tz.zone})."})
            return out
        for hh in range(15, 24):
            try:
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Krishna", 4):
                    out.append({"summary":"Karwa Chauth","date": d,
                                "desc": f"Krishna Chaturthi detected in evening ({tz.zone})."})
                    return out
            except Exception:
                pass
        d += timedelta(days=1)
    return out

def rule_diwali_bundle(lat, lon, year, tz, intervals) -> List[Dict]:
    out: List[Dict] = []
    d = date(year,9,20); end = date(year,11,20)
    diwali = None
    while d <= end:
        try:
            sr = local_sun_times(lat, lon, d, tz)[0]
            t = tithi_number_at(sr)
            if t == 30:
                noon = tz.localize(datetime(d.year, d.month, d.day, 12))
                if sidereal_solar_month_index(noon) == 6:  # Tula
                    diwali = d; break
        except Exception:
            pass
        d += timedelta(days=1)
    if diwali:
        out.append({"summary":"Diwali / Deepavali","date": diwali,
                    "desc": f"Amavasya in sidereal Libra ({tz.zone})."})
        out.append({"summary":"Govardhan Puja / Annakut","date": diwali + timedelta(days=1),
                    "desc": "Shukla Pratipada (day after Diwali)."})
        out.append({"summary":"Bhai Dooj","date": diwali + timedelta(days=2),
                    "desc": "Shukla Dwitiya (two days after Diwali)."})
    return out

def rule_ram_navami(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """
    Ram Navami: Chaitra Shukla Navami.
    Use Madhyāhna-kāla = central 1/5 of the daytime (centered at mid of sunrise/sunset).
    Pick the civil date where Navami occupies the largest fraction of that window.
    Window scanned: Mar 15 – Apr 20 (civil).
    """
    from datetime import timedelta
    out: List[Dict] = []

    start, end = date(year, 3, 15), date(year, 4, 20)
    best = None  # (score, date, details)

    d = start
    while d <= end:
        try:
            sr, ss = local_sun_times(lat, lon, d, tz)
            # Guard for polar/DST oddities
            if ss <= sr:
                ss = sr + timedelta(hours=12)

            daylen = ss - sr
            mid = sr + daylen / 2
            # Madhyāhna-kāla = 1/5 of day centered at mid
            half_window = daylen / 10
            wstart = mid - half_window
            wend   = mid + half_window

            # Sample the window every 6 minutes (~20 samples for ~2.4h window if 12h day)
            step = timedelta(minutes=6)
            samples, hits = 0, 0
            t9 = tithi_abs("Shukla", 9)

            chk = wstart
            while chk <= wend:
                if tithi_number_at(chk) == t9:
                    hits += 1
                samples += 1
                chk += step

            score = hits / max(1, samples)
            if score > 0:
                # Prefer higher score; if tie, prefer the later day (common observance tie-break)
                if (best is None) or (score > best[0]) or (score == best[0] and d > best[1]):
                    best = (score, d, f"Madhyāhna-kāla occupancy: {hits}/{samples} ≈ {score:.2%}; mid {mid.astimezone(tz).strftime('%H:%M %Z')}")
        except Exception:
            pass

        d += timedelta(days=1)

    if best:
        score, when, note = best
        out.append({
            "summary": "Ram Navami",
            "date": when,
            "desc": f"Chaitra Shukla Navami — {note}"
        })

    return out
def rule_akshaya_tritiya(lat, lon, year, tz, intervals) -> List[Dict]:
    out: List[Dict] = []
    d = date(year,4,1); end = date(year,6,1)
    while d < end:
        if _tithi_at_sunrise(lat, lon, d, tz) == tithi_abs("Shukla", 3):
            out.append({"summary":"Akshaya Tritiya","date": d,
                        "desc": f"Vaishakha Shukla Tritiya ({tz.zone})."})
            break
        d += timedelta(days=1)
    return out

def rule_guru_nanak_jayanti(lat, lon, year, tz, intervals) -> List[Dict]:
    out: List[Dict] = []
    d = date(year,10,1); end = date(year,12,1)
    while d < end:
        if _tithi_at_sunrise(lat, lon, d, tz) == tithi_abs("Shukla", 15):
            out.append({"summary":"Guru Nanak Jayanti","date": d,
                        "desc": f"Kartika Purnima at sunrise ({tz.zone})."})
            break
        d += timedelta(days=1)
    return out

def rule_holi(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """
    Holika Dahan: Phalguna Purnima evening (Mar–Apr window).
    Dhulandi (Rangwali Holi): next civil day.
    """
    out: List[Dict] = []
    start = date(year, 2, 20); end = date(year, 4, 10)

    d = start
    while d <= end:
        try:
            sr, ss = local_sun_times(lat, lon, d, tz)
            # Prefer Purnima present in the evening/night
            hit = False
            for hh in range(ss.hour, 24):  # from sunset to midnight
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 15):
                    out.append({"summary": "Holika Dahan",
                                "date": d,
                                "desc": f"Phalguna Purnima evening ({tz.zone})."})
                    out.append({"summary": "Holi / Dhulandi",
                                "date": d + timedelta(days=1),
                                "desc": "Day after Phalguna Purnima."})
                    hit = True
                    break
            if hit:
                break
            # Fallback: Purnima at sunrise → still create both
            if tithi_number_at(sr) == tithi_abs("Shukla", 15):
                out.append({"summary": "Holika Dahan",
                            "date": d,
                            "desc": f"Phalguna Purnima ({tz.zone})."})
                out.append({"summary": "Holi / Dhulandi",
                            "date": d + timedelta(days=1),
                            "desc": "Day after Phalguna Purnima."})
                break
        except Exception:
            pass
        d += timedelta(days=1)

    return out

def rule_raksha_bandhan(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """Raksha Bandhan: Shravana Purnima (Jul–Sep window, prefer sunrise; fallback hourly)."""
    out: List[Dict] = []
    start = date(year, 7, 20); end = date(year, 9, 10)

    d = start
    while d <= end:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            if tithi_number_at(sr) == tithi_abs("Shukla", 15):
                out.append({"summary": "Raksha Bandhan",
                            "date": d,
                            "desc": f"Shravana Purnima ({tz.zone})."})
                break
            # Fallback hourly scan
            for hh in range(0, 24):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 15):
                    out.append({"summary": "Raksha Bandhan",
                                "date": d,
                                "desc": f"Shravana Purnima (hour {hh:02d}), {tz.zone}."})
                    d = end  # stop
                    break
        except Exception:
            pass
        d += timedelta(days=1)

    return out

def rule_janmashtami(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """
    Janmashtami: Krishna Ashtami (Bhadrapada), prefer night occurrence (20:00–24:00).
    Window Aug 10 – Sep 30.
    """
    out: List[Dict] = []
    start = date(year, 8, 10); end = date(year, 9, 30)
    target = tithi_abs("Krishna", 8)

    d = start
    while d <= end:
        try:
            # Prefer evening/night hours first
            for hh in range(20, 24):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == target:
                    out.append({"summary": "Janmashtami",
                                "date": d,
                                "desc": f"Krishna Ashtami (night), {tz.zone}."})
                    return out
            # Fallback: if present any time in the day, accept
            sr, _ = local_sun_times(lat, lon, d, tz)
            if tithi_number_at(sr) == target:
                out.append({"summary": "Janmashtami",
                            "date": d,
                            "desc": f"Krishna Ashtami (sunrise), {tz.zone}."})
                return out
            for hh in range(0, 20):
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == target:
                    out.append({"summary": "Janmashtami",
                                "date": d,
                                "desc": f"Krishna Ashtami (hour {hh:02d}), {tz.zone}."})
                    return out
        except Exception:
            pass
        d += timedelta(days=1)

    return out

def rule_hanuman_jayanti(lat, lon, year, tz, _intervals_unused) -> List[Dict]:
    """Hanuman Jayanti (Marathi): Chaitra Purnima (Mar–May window)."""
    out: List[Dict] = []
    start = date(year, 3, 20); end = date(year, 5, 10)

    d = start
    while d <= end:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            if tithi_number_at(sr) == tithi_abs("Shukla", 15):
                out.append({"summary": "Hanuman Jayanti",
                            "date": d,
                            "desc": f"Chaitra Purnima ({tz.zone})."})
                break
            for hh in range(0, 24):  # hourly fallback
                chk = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                if tithi_number_at(chk) == tithi_abs("Shukla", 15):
                    out.append({"summary": "Hanuman Jayanti",
                                "date": d,
                                "desc": f"Chaitra Purnima (hour {hh:02d}), {tz.zone}."})
                    d = end
                    break
        except Exception:
            pass
        d += timedelta(days=1)

    return out

FESTIVALS = [
    {"key":"makara_sankranti",  "rule": rule_makara_sankranti},
    {"key":"hariyali_teej",     "rule": rule_hariyali_teej},
    {"key":"hartalika_teej",    "rule": rule_hartalika_teej},
    {"key":"nag_panchami",      "rule": rule_nag_panchami},
    {"key":"ganesh_chaturthi",  "rule": rule_ganesh_chaturthi},
    {"key":"navaratri_set",     "rule": rule_navaratri_set},
    {"key":"pitru_paksha",      "rule": rule_pitru_paksha},
    {"key":"karwa_chauth",      "rule": rule_karwa_chauth},
    {"key":"diwali_bundle",     "rule": rule_diwali_bundle},
    {"key":"ram_navami",        "rule": rule_ram_navami},
    {"key":"akshaya_tritiya",   "rule": rule_akshaya_tritiya},
    {"key":"guru_nanak",        "rule": rule_guru_nanak_jayanti},
    {"key":"maha_shivratri",    "rule": rule_mahashivratri},
    {"key":"holi",              "rule": rule_holi},
    {"key":"raksha_bandhan",    "rule": rule_raksha_bandhan},
    {"key":"janmashtami",       "rule": rule_janmashtami},
    {"key":"hanuman_jayanti",   "rule": rule_hanuman_jayanti},
    {"key":"gudi_padwa",        "rule": rule_gudi_padwa},   # Add back if missing
]

def festivals_for_year(lat: float, lon: float, year: int, which: Optional[str] = "all") -> List[Dict]:
    tz = iana_timezone_for(lat, lon)
    intervals = amanta_lunation_intervals(year)
    chosen = FESTIVALS if which in (None,"all") else [f for f in FESTIVALS if f["key"] in which.split(",")]
    out: List[Dict] = []
    for f in chosen:
        out += f["rule"](lat, lon, year, tz, intervals)
    return out

# ---------------- Orchestrator -----------------
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