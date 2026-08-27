"""Incremental pull from Garmin Connect + Open-Meteo → local parquet/json.

Read-only API calls only. Run interactively (prompts for credentials on
first run; afterwards resumes from the cached token store).

    python pull.py

Then run `python compute.py` to derive metrics, and `streamlit run dashboard.py`.
"""

import datetime as dt
import getpass
import json
import sys
import time

import pandas as pd
import requests
from garminconnect import Garmin

import config as C

ACTIVITIES = C.DATA / "activities.parquet"
WEATHER = C.DATA / "weather.parquet"
VO2 = C.DATA / "vo2max.parquet"
RACE_PRED = C.DATA / "race_predictions.parquet"
DAILY = C.DATA / "daily_health.parquet"
ZONES = C.DATA / "hr_zones.json"


def login() -> Garmin:
    try:
        g = Garmin()
        g.login(C.TOKENSTORE)
        print("Logged in from cached tokens.")
        return g
    except Exception:
        pass
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    g = Garmin(email, password)
    g.login(C.TOKENSTORE)  # persists tokens to TOKENSTORE on success
    print("Logged in; tokens cached.")
    return g


def _year_chunks(start: str, end: str):
    """Yield (start, end) date-string pairs no longer than ~360 days."""
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    while s <= e:
        c = min(s + dt.timedelta(days=359), e)
        yield s.isoformat(), c.isoformat()
        s = c + dt.timedelta(days=1)


# --- Activities ---------------------------------------------------------------

def pull_activities(g: Garmin) -> pd.DataFrame:
    prev = pd.read_parquet(ACTIVITIES) if ACTIVITIES.exists() else None
    start = C.START_DATE
    if prev is not None and len(prev):
        # overlap 7 days to catch late-synced activities
        start = (pd.to_datetime(prev["start_time_local"]).max().date()
                 - dt.timedelta(days=7)).isoformat()
    end = dt.date.today().isoformat()
    print(f"Fetching running activities {start} → {end} ...")
    acts = g.get_activities_by_date(start, end, activitytype="running")
    rows = []
    for a in acts:
        rows.append({
            "activity_id": int(a["activityId"]),
            "name": a.get("activityName"),
            "type_key": (a.get("activityType") or {}).get("typeKey"),
            "event_type": (a.get("eventType") or {}).get("typeKey"),
            "start_time_local": a.get("startTimeLocal"),
            "start_time_gmt": a.get("startTimeGMT"),
            "distance_m": a.get("distance"),
            "duration_s": a.get("duration"),
            "moving_duration_s": a.get("movingDuration"),
            "elevation_gain_m": a.get("elevationGain"),
            "avg_hr": a.get("averageHR"),
            "max_hr": a.get("maxHR"),
            "avg_speed_mps": a.get("averageSpeed"),
            "start_lat": a.get("startLatitude"),
            "start_lon": a.get("startLongitude"),
            # running dynamics (availability depends on device/accessories)
            "avg_cadence_spm": a.get("averageRunningCadenceInStepsPerMinute"),
            "avg_stride_len_cm": a.get("avgStrideLength"),
            "avg_gct_ms": a.get("avgGroundContactTime"),
            "avg_vert_osc": a.get("avgVerticalOscillation"),
            "avg_vert_ratio": a.get("avgVerticalRatio"),
            "avg_gct_balance": a.get("avgGroundContactBalance"),
            "avg_power_w": a.get("avgPower"),
        })
    new = pd.DataFrame(rows)
    df = pd.concat([prev, new]) if prev is not None else new
    df = (df.drop_duplicates("activity_id", keep="last")
            .sort_values("start_time_local")
            .reset_index(drop=True))
    df.to_parquet(ACTIVITIES, index=False)
    print(f"  {len(new)} fetched, {len(df)} total on disk.")
    return df


# --- Per-run streams ----------------------------------------------------------

def parse_details(d: dict) -> pd.DataFrame:
    idx = {m["key"]: m["metricsIndex"] for m in (d.get("metricDescriptors") or [])}
    rows = d.get("activityDetailMetrics") or []

    def col(key):
        i = idx.get(key)
        return [r["metrics"][i] if i is not None else None for r in rows]

    return pd.DataFrame({
        "t": col("sumDuration"),            # seconds since start
        "hr": col("directHeartRate"),
        "speed_mps": col("directSpeed"),
        "elev_m": col("directElevation"),
    })


def pull_streams(g: Garmin, df: pd.DataFrame):
    C.STREAMS.mkdir(parents=True, exist_ok=True)
    missing = [aid for aid in df["activity_id"]
               if not (C.STREAMS / f"{aid}.parquet").exists()]
    print(f"Fetching streams for {len(missing)} activities ...")
    for n, aid in enumerate(missing, 1):
        try:
            s = parse_details(g.get_activity_details(str(aid)))
        except Exception as e:
            print(f"  ! {aid}: {e}")
            continue
        s.to_parquet(C.STREAMS / f"{aid}.parquet", index=False)
        if n % 20 == 0:
            print(f"  {n}/{len(missing)}")
        time.sleep(0.3)  # be polite to the API


# --- Weather (Open-Meteo, keyed by GPS start + GMT start hour) ---------------

def _fetch_weather(lat, lon, day: str, hour: int):
    """Return (temp_f, dew_f) for the hour nearest run start, or (None, None).

    Tries the archive (ERA5) API first; recent days (~5-day lag) fall back to
    the forecast API's recent-past window.
    """
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": day, "end_date": day,
        "hourly": "temperature_2m,dew_point_2m",
        "temperature_unit": "fahrenheit", "timezone": "UTC",
    }
    for base in ("https://archive-api.open-meteo.com/v1/archive",
                 "https://api.open-meteo.com/v1/forecast"):
        try:
            r = requests.get(base, params=params, timeout=30)
            r.raise_for_status()
            h = r.json().get("hourly") or {}
            temps, dews = h.get("temperature_2m") or [], h.get("dew_point_2m") or []
            if hour < len(dews) and dews[hour] is not None:
                return temps[hour], dews[hour]
        except requests.RequestException:
            pass
    return None, None


def pull_weather(df: pd.DataFrame):
    prev = pd.read_parquet(WEATHER) if WEATHER.exists() else pd.DataFrame(
        columns=["activity_id", "temp_f", "dew_point_f"])
    have = set(prev["activity_id"])
    todo = df[df["activity_id"].map(lambda a: a not in have)
              & df["start_lat"].notna() & df["start_time_gmt"].notna()]
    print(f"Fetching weather for {len(todo)} runs ...")
    rows = []
    for _, r in todo.iterrows():
        ts = pd.to_datetime(r["start_time_gmt"])
        temp, dew = _fetch_weather(r["start_lat"], r["start_lon"],
                                   ts.date().isoformat(), ts.hour)
        if dew is not None:
            rows.append({"activity_id": r["activity_id"],
                         "temp_f": temp, "dew_point_f": dew})
        time.sleep(0.2)
    out = pd.concat([prev, pd.DataFrame(rows)]) if rows else prev
    out.to_parquet(WEATHER, index=False)
    print(f"  {len(rows)} added, {len(out)} total.")


# --- VO2max / race predictions / daily health / zones ------------------------

def pull_vo2(g: Garmin):
    rows = []
    for s, e in _year_chunks(C.START_DATE, dt.date.today().isoformat()):
        data = g.get_max_metrics_range(s, e) or []
        for item in data:
            gen = item.get("generic") or {}
            v = gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue")
            if gen.get("calendarDate") and v:
                rows.append({"date": gen["calendarDate"], "vo2max": v})
    pd.DataFrame(rows).drop_duplicates("date").to_parquet(VO2, index=False)
    print(f"VO2max: {len(rows)} days.")


def pull_race_predictions(g: Garmin):
    rows = []
    for s, e in _year_chunks(C.START_DATE, dt.date.today().isoformat()):
        data = g.get_race_predictions(s, e, "daily") or []
        if isinstance(data, dict):
            data = data.get("racePredictions") or [data]
        for item in data:
            if item.get("calendarDate"):
                rows.append({"date": item["calendarDate"],
                             "time_5k_s": item.get("time5K"),
                             "time_10k_s": item.get("time10K"),
                             "time_half_s": item.get("timeHalfMarathon"),
                             "time_full_s": item.get("timeMarathon")})
    pd.DataFrame(rows).drop_duplicates("date").to_parquet(RACE_PRED, index=False)
    print(f"Race predictions: {len(rows)} days.")


def pull_daily_health(g: Garmin):
    rhr_rows, hrv_rows = [], []
    for s, e in _year_chunks(C.START_DATE, dt.date.today().isoformat()):
        for r in g.get_rhr_daily(s, e) or []:
            rhr_rows.append({"date": r["calendarDate"], "rhr": r["value"]})
        hrv = g.get_hrv_data_range(s, e) or {}
        for h in hrv.get("hrvSummaries") or []:
            if h.get("calendarDate"):
                hrv_rows.append({"date": h["calendarDate"],
                                 "hrv": h.get("lastNightAvg")})
    rhr = pd.DataFrame(rhr_rows).drop_duplicates("date")
    hrv = pd.DataFrame(hrv_rows).drop_duplicates("date")
    if len(rhr) and len(hrv):
        daily = rhr.merge(hrv, on="date", how="outer")
    else:
        daily = rhr if len(rhr) else hrv
    daily.sort_values("date").to_parquet(DAILY, index=False)
    print(f"Daily health: {len(daily)} days (rhr {len(rhr)}, hrv {len(hrv)}).")


def pull_zones(g: Garmin):
    zones = g.get_heart_rate_zones()
    chosen = None
    for z in zones or []:
        if (z.get("sport") or "").upper() == "RUNNING":
            chosen = z
    if chosen is None and zones:
        chosen = next((z for z in zones
                       if (z.get("sport") or "").upper() == "DEFAULT"), zones[0])
    if not chosen or "zone2Floor" not in chosen or "zone3Floor" not in chosen:
        sys.exit(f"Could not parse HR zones from API response: {zones!r}\n"
                 "Set z2_low/z2_high manually in data/hr_zones.json.")
    out = {
        "z2_low": chosen["zone2Floor"],
        "z2_high": chosen["zone3Floor"] - 1,
        "floors": [chosen.get(f"zone{i}Floor") for i in range(1, 6)],
        "max_hr_used": chosen.get("maxHeartRateUsed"),
        "sport": chosen.get("sport"),
        "raw": zones,
    }
    ZONES.write_text(json.dumps(out, indent=2))
    print(f"HR zones ({out['sport']}): Z2 = {out['z2_low']}–{out['z2_high']} bpm, "
          f"max HR {out['max_hr_used']}.")


def main():
    C.DATA.mkdir(exist_ok=True)
    g = login()
    pull_zones(g)
    df = pull_activities(g)
    pull_streams(g, df)
    pull_weather(df)
    pull_vo2(g)
    pull_race_predictions(g)
    pull_daily_health(g)
    print("\nDone. Next: python compute.py")


if __name__ == "__main__":
    main()
