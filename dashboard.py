"""Aerobic efficiency dashboard. Reads data/ files only — never the API.

    streamlit run dashboard.py
"""

import datetime as dt
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as C
from trendlib import fmt_pace, headline_delta, rolling_fit

st.set_page_config(page_title="Aerobic Efficiency", layout="wide")

BAND_COLORS = {"<55°F": "#4c9be8", "55–65°F": "#e8a13c", "65°F+": "#d9534f",
               "unknown": "#999999"}


@st.cache_data
def load():
    runs = pd.read_parquet(C.DATA / "runs.parquet")
    runs["date_dt"] = pd.to_datetime(runs["date"])
    vo2 = pd.read_parquet(C.DATA / "vo2max.parquet")
    pred = pd.read_parquet(C.DATA / "race_predictions.parquet")
    daily = pd.read_parquet(C.DATA / "daily_health.parquet")
    zones = json.loads((C.DATA / "hr_zones.json").read_text())
    return runs, vo2, pred, daily, zones


runs, vo2, pred, daily, zones = load()
steady_all = runs[runs["steady_z2"]].copy()

# --- Sidebar: dew point filter + gate report ---------------------------------
st.sidebar.header("Filters")
band_choice = st.sidebar.radio(
    "Dew point band (efficiency trend)",
    ["All"] + [b[0] for b in C.DEW_BANDS],
    help="Filter the EF pool to one humidity band so seasonal weather shifts "
         "can't masquerade as fitness changes.")
steady = steady_all if band_choice == "All" else steady_all[steady_all["dew_band"] == band_choice]

with st.sidebar.expander("Steady-Z2 gate report"):
    st.caption(f"Z2 = {zones['z2_low']}–{zones['z2_high']} bpm (from Garmin). "
               f"{len(steady_all)} of {len(runs)} runs eligible.")
    excl = runs.loc[~runs["steady_z2"], "failed_gates"].str.split(",").explode()
    st.dataframe(excl.value_counts().rename("runs"), width='stretch')

# --- Headline row -------------------------------------------------------------
trend = rolling_fit(steady)
race_date = dt.date.fromisoformat(C.RACE_DATE)

now_pace, delta_str = headline_delta(trend)

long_steady = steady_all[steady_all["eligible_time_s"] >= C.DECOUPLING_MIN_DURATION_S]
latest_dec = long_steady.iloc[-1]["decoupling_pct"] if len(long_steady) else np.nan
cur_vo2 = vo2.sort_values("date").iloc[-1]["vo2max"] if len(vo2) else np.nan

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Pace @ {C.REF_HR} bpm", f"{fmt_pace(now_pace)} /mi", delta_str,
          delta_color="inverse")
c2.metric("Latest long-run decoupling", f"{latest_dec:+.1f}%" if not np.isnan(latest_dec) else "—",
          "negative = good" if latest_dec < 0 else None, delta_color="off")
c3.metric("VO₂max", f"{cur_vo2:.1f}" if not np.isnan(cur_vo2) else "—")
c4.metric("Days to 10K", f"{(race_date - dt.date.today()).days}", C.RACE_DATE)

# --- Chart 1: efficiency trend ------------------------------------------------
st.subheader(f"Predicted pace at {C.REF_HR} bpm — steady Z2 runs")
fig = go.Figure()
for band in [b[0] for b in C.DEW_BANDS] + ["unknown"]:
    pts = steady[steady["dew_band"] == band]
    if not len(pts):
        continue
    fig.add_trace(go.Scatter(
        x=pts["date_dt"], y=pts["pace_at_ref"], mode="markers", name=band,
        marker=dict(color=BAND_COLORS[band], size=7, opacity=0.75),
        customdata=np.stack([pts["name"], pts["eff_avg_hr"].round(0),
                             pts["eff_pace_min_mi"].map(fmt_pace),
                             pts["distance_mi"].round(1)], axis=-1),
        hovertemplate="%{customdata[0]}<br>%{x|%b %d %Y}<br>"
                      "actual %{customdata[2]}/mi @ %{customdata[1]} bpm · "
                      "%{customdata[3]} mi<extra>" + band + "</extra>"))
if len(trend):
    conf = trend[trend["confident"]]
    fig.add_trace(go.Scatter(x=trend["date_dt"], y=trend["pace"], mode="lines",
                             name=f"{C.FIT_WINDOW_DAYS}-day fit",
                             line=dict(color="#222222", width=3)))
    lowc = trend[~trend["confident"]]
    if len(lowc):
        fig.add_trace(go.Scatter(x=lowc["date_dt"], y=lowc["pace"], mode="markers",
                                 name="low confidence (<5 runs)",
                                 marker=dict(color="#222222", symbol="circle-open")))
fig.update_yaxes(autorange="reversed", title="min/mi (lower = faster)",
                 tickformat=None)
fig.update_layout(height=450, margin=dict(t=10), legend=dict(orientation="h"))
st.plotly_chart(fig, width='stretch')
st.caption("Scatter = each steady run's pace scaled to the reference HR by its own "
           "efficiency factor; line = pace-vs-HR regression over a trailing "
           f"{C.FIT_WINDOW_DAYS}-day window, evaluated at {C.REF_HR} bpm. Colors are "
           "dew point at run start (Open-Meteo, not the watch sensor).")

# --- Chart 2: aerobic decoupling ---------------------------------------------
st.subheader("Aerobic decoupling (Pa:HR) — steady runs ≥ 40 min")
if len(long_steady):
    fig2 = go.Figure()
    good = long_steady["decoupling_pct"] <= 5
    fig2.add_trace(go.Scatter(
        x=long_steady["date_dt"], y=long_steady["decoupling_pct"], mode="markers",
        marker=dict(color=np.where(long_steady["decoupling_pct"] < 0, "#2e8b57",
                    np.where(good, "#4c9be8", "#d9534f")), size=8),
        customdata=long_steady["name"], name="runs",
        hovertemplate="%{customdata}<br>%{x|%b %d %Y}: %{y:.1f}%<extra></extra>"))
    roll = long_steady.set_index("date_dt")["decoupling_pct"].rolling("56D").mean()
    fig2.add_trace(go.Scatter(x=roll.index, y=roll.values, mode="lines",
                              name="8-wk avg", line=dict(color="#222222")))
    fig2.add_hline(y=5, line_dash="dash", line_color="#d9534f",
                   annotation_text="5% — aerobic durability threshold")
    fig2.add_hline(y=0, line_dash="dot", line_color="#2e8b57",
                   annotation_text="negative = HR fell relative to pace (good)")
    fig2.update_layout(height=350, margin=dict(t=10),
                       yaxis_title="1st vs 2nd half efficiency drift %")
    st.plotly_chart(fig2, width='stretch')
else:
    st.info("No steady runs ≥ 40 min yet.")

# --- Chart 3: VO2max + 10K prediction ----------------------------------------
st.subheader("Garmin VO₂max & 10K race prediction")
col_a, col_b = st.columns(2)
with col_a:
    f = go.Figure(go.Scatter(x=pd.to_datetime(vo2["date"]), y=vo2["vo2max"],
                             mode="lines", line=dict(color="#4c9be8")))
    f.add_vline(x=pd.Timestamp(race_date).timestamp() * 1000, line_dash="dash",
                annotation_text="race")
    f.update_layout(height=300, margin=dict(t=10), yaxis_title="VO₂max")
    st.plotly_chart(f, width='stretch')
with col_b:
    p = pred.dropna(subset=["time_10k_s"])
    f = go.Figure(go.Scatter(x=pd.to_datetime(p["date"]), y=p["time_10k_s"] / 60,
                             mode="lines", line=dict(color="#e8a13c")))
    f.add_vline(x=pd.Timestamp(race_date).timestamp() * 1000, line_dash="dash",
                annotation_text="race")
    f.update_yaxes(autorange="reversed", title="predicted 10K (min)")
    f.update_layout(height=300, margin=dict(t=10))
    st.plotly_chart(f, width='stretch')

# --- Context panels -----------------------------------------------------------
st.subheader("Context")
k1, k2, k3 = st.columns(3)
with k1:
    st.caption("Weekly volume (mi)")
    wk = runs.set_index("date_dt")["distance_mi"].resample("W").sum()
    st.plotly_chart(go.Figure(go.Bar(x=wk.index, y=wk.values,
                    marker_color="#4c9be8")).update_layout(
                    height=250, margin=dict(t=5)), width='stretch')
with k2:
    st.caption("HR zone distribution (weekly % of run time)")
    zcols = [c for c in runs.columns if c.startswith("z") and c.endswith("_s")]
    zt = runs.set_index("date_dt")[zcols].resample("W").sum()
    share = zt.div(zt.sum(axis=1), axis=0) * 100
    fz = go.Figure()
    palette = ["#9ec9ef", "#4c9be8", "#2e8b57", "#e8a13c", "#d9534f"]
    for i, c in enumerate(zcols):
        fz.add_trace(go.Scatter(x=share.index, y=share[c], stackgroup="one",
                                name=f"Z{i+1}", line=dict(width=0),
                                fillcolor=palette[i % 5]))
    fz.update_layout(height=250, margin=dict(t=5), showlegend=False,
                     yaxis=dict(range=[0, 100]))
    st.plotly_chart(fz, width='stretch')
with k3:
    st.caption("Resting HR & HRV")
    dd = daily.copy()
    dd["date"] = pd.to_datetime(dd["date"])
    fh = go.Figure()
    if "rhr" in dd:
        fh.add_trace(go.Scatter(x=dd["date"], y=dd["rhr"].rolling(7, min_periods=1).mean(),
                                name="RHR (7d)", line=dict(color="#d9534f")))
    if "hrv" in dd:
        fh.add_trace(go.Scatter(x=dd["date"], y=dd["hrv"].rolling(7, min_periods=1).mean(),
                                name="HRV (7d)", line=dict(color="#2e8b57"), yaxis="y2"))
    fh.update_layout(height=250, margin=dict(t=5),
                     yaxis=dict(title="RHR"),
                     yaxis2=dict(title="HRV", overlaying="y", side="right"),
                     legend=dict(orientation="h"))
    st.plotly_chart(fh, width='stretch')
