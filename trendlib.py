"""Shared trend math for the Streamlit dashboard and the static export."""

import numpy as np
import pandas as pd

import config as C


def fmt_pace(p):
    if p is None or np.isnan(p):
        return "—"
    m, s = int(p), round((p - int(p)) * 60)
    if s == 60:
        m, s = m + 1, 0
    return f"{m}:{s:02d}"


def rolling_fit(steady: pd.DataFrame) -> pd.DataFrame:
    """Predicted pace at REF_HR per steady-run date: pace-vs-HR fit over a
    trailing window; falls back to window mean of per-run implied paces
    (flagged low-confidence) when the fit would be under-determined."""
    out = []
    for d in sorted(steady["date_dt"].unique()):
        win = steady[(steady["date_dt"] > d - pd.Timedelta(days=C.FIT_WINDOW_DAYS))
                     & (steady["date_dt"] <= d)]
        hr, pace = win["eff_avg_hr"].values, win["eff_pace_min_mi"].values
        if len(win) >= C.FIT_MIN_RUNS and np.ptp(hr) >= C.FIT_MIN_HR_SPREAD:
            slope, icept = np.polyfit(hr, pace, 1)
            out.append({"date_dt": d, "pace": slope * C.REF_HR + icept,
                        "confident": True, "n": len(win)})
        elif len(win):
            out.append({"date_dt": d, "pace": win["pace_at_ref"].mean(),
                        "confident": False, "n": len(win)})
    return pd.DataFrame(out)


def headline_delta(trend: pd.DataFrame):
    """(current pace, delta string vs 8 weeks ago) from a rolling_fit result."""
    if not len(trend):
        return np.nan, None
    now_pace = trend.iloc[-1]["pace"]
    target = trend.iloc[-1]["date_dt"] - pd.Timedelta(days=56)
    past = trend[abs(trend["date_dt"] - target) <= pd.Timedelta(days=10)]
    if not len(past):
        return now_pace, None
    d = now_pace - past.iloc[-1]["pace"]
    return now_pace, f"{'+' if d >= 0 else '−'}{fmt_pace(abs(d))} vs 8 wk ago"
