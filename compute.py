"""Derive per-run metrics from pulled data → data/runs.parquet.

Applies the steady-Z2 eligibility gates (see README / config.py), computes
per-run efficiency, aerobic decoupling, and time-in-zone, and joins weather.
Pure file-in / file-out — never touches the API.

    python compute.py
"""

import json

import numpy as np
import pandas as pd

import config as C

M_PER_MI = 1609.344
FT_PER_M = 3.28084


def pace_min_per_mi(speed_mps: float) -> float:
    return M_PER_MI / speed_mps / 60.0


def analyze_streams(aid: int, band_lo: float, band_hi: float, floors: list):
    """Compute stream-derived metrics for one run. Returns dict (may be sparse)."""
    path = C.STREAMS / f"{aid}.parquet"
    if not path.exists():
        return {"has_streams": False}
    s = pd.read_parquet(path).dropna(subset=["t", "hr", "speed_mps"])
    if len(s) < 30:
        return {"has_streams": False}
    s = s.sort_values("t").reset_index(drop=True)

    # per-sample duration weight, clipped so pauses don't dominate
    dts = s["t"].diff().bfill().clip(0.1, 30.0)
    step = float(dts.median())

    moving = s["speed_mps"] >= C.MIN_MOVING_SPEED_MPS
    warm = s["t"] >= C.WARMUP_DISCARD_S
    elig = moving & warm
    elig_time = float(dts[elig].sum())
    if elig_time < 60:
        return {"has_streams": True, "eligible_time_s": elig_time}

    w = dts[elig]
    hr = s.loc[elig, "hr"]
    speed = s.loc[elig, "speed_mps"]

    avg_hr = float(np.average(hr, weights=w))
    avg_speed = float(np.average(speed, weights=w))

    # pace steadiness: CV of ~30s-smoothed pace over eligible samples
    win = max(3, int(round(30.0 / step)))
    speed_smooth = s["speed_mps"].rolling(win, center=True, min_periods=1).mean()
    pace = 1.0 / speed_smooth[elig].clip(lower=0.1)
    pace_cv = float(pace.std() / pace.mean())

    frac_band = float(w[(hr >= band_lo) & (hr <= band_hi)].sum() / w.sum())

    # aerobic decoupling: EF (speed/HR) of first vs second half of eligible time
    cum = dts[elig].cumsum()
    first = cum <= elig_time / 2
    def ef(mask):
        return (np.average(speed[mask], weights=w[mask])
                / np.average(hr[mask], weights=w[mask]))
    ef1, ef2 = ef(first), ef(~first)
    decoupling_pct = float((ef1 - ef2) / ef1 * 100.0)

    # time in each configured zone (whole run, moving samples) for context panel
    zone_secs = {}
    edges = [f for f in floors if f is not None] + [999]
    for i in range(len(edges) - 1):
        mask = moving & (s["hr"] >= edges[i]) & (s["hr"] < edges[i + 1])
        zone_secs[f"z{i + 1}_s"] = float(dts[mask].sum())

    return {
        "has_streams": True,
        "eligible_time_s": elig_time,
        "eff_avg_hr": avg_hr,
        "eff_avg_speed_mps": avg_speed,
        "eff_pace_min_mi": pace_min_per_mi(avg_speed),
        "pace_cv": pace_cv,
        "frac_time_band": frac_band,
        "decoupling_pct": decoupling_pct,
        **zone_secs,
    }


def gate_run(row) -> list:
    """Return list of failed-gate names (empty list = steady aerobic run)."""
    lo, hi = C.EASY_HR_BAND
    fails = []
    if row["type_key"] != "running" or pd.isna(row["start_lat"]):
        fails.append("not_outdoor_gps_run")
    if row.get("event_type") == "race":
        fails.append("race")
    name = (row.get("name") or "").lower()
    if any(k in name for k in C.WORKOUT_NAME_KEYWORDS):
        fails.append("named_workout")
    if not row.get("has_streams"):
        fails.append("no_streams")
        return fails
    if (row.get("eligible_time_s") or 0) < C.MIN_DURATION_S:
        fails.append("too_short")
        return fails
    dist_mi = (row["distance_m"] or 0) / M_PER_MI
    if dist_mi > 0 and (row["elevation_gain_m"] or 0) * FT_PER_M / dist_mi > C.MAX_ELEV_GAIN_FT_PER_MI:
        fails.append("too_hilly")
    if not (lo <= row["eff_avg_hr"] <= hi):
        fails.append("avg_hr_outside_easy_band")
    if row["frac_time_band"] < C.MIN_TIME_IN_BAND:
        fails.append("time_in_band_low")
    if row["pace_cv"] > C.MAX_PACE_CV:
        fails.append("pace_too_variable")
    return fails


def main():
    zones = json.loads((C.DATA / "hr_zones.json").read_text())
    lo, hi = C.EASY_HR_BAND
    acts = pd.read_parquet(C.DATA / "activities.parquet")
    weather = pd.read_parquet(C.DATA / "weather.parquet")

    metrics = [analyze_streams(aid, lo, hi, C.effective_floors(zones))
               for aid in acts["activity_id"]]
    df = pd.concat([acts.reset_index(drop=True), pd.DataFrame(metrics)], axis=1)
    df = df.merge(weather, on="activity_id", how="left")

    df["failed_gates"] = df.apply(gate_run, axis=1)
    df["steady_z2"] = df["failed_gates"].map(len) == 0
    df["failed_gates"] = df["failed_gates"].map(",".join)
    df["dew_band"] = df["dew_point_f"].map(C.dew_band)
    df["date"] = pd.to_datetime(df["start_time_local"]).dt.date.astype(str)
    df["distance_mi"] = df["distance_m"] / M_PER_MI
    # per-run implied pace at REF_HR via EF scaling (scatter points; the trend
    # line in the dashboard uses a real pace-vs-HR fit instead)
    df["pace_at_ref"] = np.nan
    ok = df["steady_z2"] & df["eff_avg_hr"].notna()
    df.loc[ok, "pace_at_ref"] = df.loc[ok].apply(
        lambda r: pace_min_per_mi(r["eff_avg_speed_mps"] / r["eff_avg_hr"] * C.REF_HR),
        axis=1,
    )

    df.to_parquet(C.DATA / "runs.parquet", index=False)

    n = len(df)
    print(f"{n} runs → {df['steady_z2'].sum()} steady Z2 runs.")
    print("Exclusions by gate (a run can fail several):")
    counts = df.loc[~df["steady_z2"], "failed_gates"].str.split(",").explode().value_counts()
    for gate, c in counts.items():
        print(f"  {gate}: {c}")
    print("\nDone. Next: streamlit run dashboard.py")


if __name__ == "__main__":
    main()
