# scripts/debug_ganesh.py
from datetime import date, datetime, timedelta
from typing import Optional

import pytz

from src.astronomy import (
    iana_timezone_for, local_sun_times, local_moonrise,
    tithi_number_at, tithi_abs,
    amanta_lunation_intervals, amanta_month_map_for_year,
)

def _local_range_from_interval(tz, iv):
    # iv is a NamedTuple: (start_utc, end_utc[, ...])
    start_local = iv.start_utc.astimezone(tz).date()
    end_local   = (iv.end_utc - timedelta(seconds=1)).astimezone(tz).date()
    return start_local, end_local

def debug_ganesh_for_city(lat: float, lon: float, year: int):
    tz = iana_timezone_for(lat, lon)
    print(f"\n=== Ganesh Chaturthi debug for {year} at lat={lat}, lon={lon}, tz={tz.zone} ===")

    # 0) Build month map once (maps every civil date -> amānta month name)
    month_map = amanta_month_map_for_year(lat, lon, year)

    # 1) Inspect lunation intervals and pick the one whose *local* dates map mostly to “Bhadrapada”
    intervals = amanta_lunation_intervals(year)

    print("\n-- Lunation intervals (local) + inferred amānta month name --")
    target = None
    for iv in intervals:
        try:
            info = iv._asdict()            # works for typing.NamedTuple
        except AttributeError:
            info = (iv.start_utc, iv.end_utc)
        d0, d1 = _local_range_from_interval(tz, iv)
        # infer the month name by sampling the mid date of the interval
        mid = d0 + (d1 - d0) // 2
        name = month_map.get(mid, "Unknown")
        print(f"  {d0} → {d1}  | name≈ {name}  | raw={info}")
        if name == "Bhadrapada":
            target = iv

    if not target:
        print("Could not find a Bhadrapada interval for this civil year. "
              "If you see Unknown above, month mapping may be empty.")
        return

    d0, d1 = _local_range_from_interval(tz, target)
    print(f"\n-- Searching within Bhadrapada interval: {d0} .. {d1} (local {tz.zone}) --")

    def fmt(dt): return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
    found: Optional[date] = None
    d = d0
    while d <= d1:
        try:
            sr, _ = local_sun_times(lat, lon, d, tz)
            t_sr = tithi_number_at(sr)
        except Exception as e:
            print(f"{d}  sunrise error: {e}")
            d += timedelta(days=1)
            continue

        mr = local_moonrise(lat, lon, d, tz)
        t_mr = (tithi_number_at(mr) if mr else None)

        hourly_hit = None
        if t_sr != tithi_abs("Shukla", 4) and t_mr != tithi_abs("Shukla", 4):
            for hh in range(0, 24):
                try:
                    dt = tz.localize(datetime(d.year, d.month, d.day, hh, 0))
                    if tithi_number_at(dt) == tithi_abs("Shukla", 4):
                        hourly_hit = dt
                        break
                except Exception:
                    pass

        parts = [f"{d}  SR:{t_sr:02d} ({fmt(sr)})"]
        if mr:
            parts.append(f"MR:{t_mr:02d} ({fmt(mr)})")
        if hourly_hit:
            parts.append(f"HIT@{hourly_hit.strftime('%H:%M')}")
        print("  ".join(parts))

        # Pick rule for Ganesh Chaturthi:
        if t_mr == tithi_abs("Shukla", 4):
            print(f"--> PICK (moonrise match): {d}")
            found = d
            break
        if t_sr == tithi_abs("Shukla", 4) and found is None:
            print(f"--> PICK (sunrise match): {d}")
            found = d
            break
        if hourly_hit and found is None:
            print(f"--> PICK (hourly fallback): {d}")
            found = d
            break

        d += timedelta(days=1)

    if not found:
        print("\nNo Shukla Chaturthi found inside the inferred Bhadrapada interval.")
        print("Try the wider seasonal scan (Jul 25–Sep 30) to double-check.")
    else:
        print(f"\nGanesh Chaturthi (detected) => {found} (local {tz.zone})")

if __name__ == "__main__":
    # Stockholm (your case)
    debug_ganesh_for_city(59.33, 18.06, 2025)
    # Mumbai sanity check (uncomment if you want)
    # debug_ganesh_for_city(19.0760, 72.8777, 2025)