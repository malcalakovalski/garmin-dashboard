"""Render the dashboard as one self-contained static page → site/index.html.

Reads data/ files only. The dew-point filter is client-side: a trend line is
precomputed per band and Plotly buttons toggle trace visibility.

    python export_static.py
"""

import datetime as dt
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import config as C
from trendlib import fmt_pace, headline_delta, rolling_fit

SITE = C.ROOT / "site"
BAND_COLORS = {"<55°F": "#4c9be8", "55–65°F": "#e8a13c", "65°F+": "#d9534f",
               "unknown": "#999999"}
BANDS = [b[0] for b in C.DEW_BANDS]

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aerobic Efficiency</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body {{ font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 1200px;
        margin: 0 auto; padding: 16px; color: #222; }}
 h1 {{ font-size: 1.3rem; }} h2 {{ font-size: 1.05rem; margin: 24px 0 4px; }}
 .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr));
          gap: 12px; }}
 .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 14px 18px; }}
 .card .label {{ font-size: .8rem; color: #666; }}
 .card .value {{ font-size: 2rem; font-weight: 650; }}
 .card .delta {{ font-size: .85rem; color: #2e8b57; }}
 .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
 .grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
 @media (max-width: 900px) {{ .grid2, .grid3 {{ grid-template-columns: 1fr; }} }}
 .caption {{ font-size: .8rem; color: #666; }}
 footer {{ margin-top: 32px; font-size: .75rem; color: #999; }}
</style></head><body>
<h1>Am I gaining aerobic efficiency?</h1>
<div class="cards">{cards}</div>
{body}
<footer>Generated {generated} · steady-Z2 gates: outdoor GPS · no races ·
≥25 min after 5-min warmup discard · avg HR in Z2 and ≥80% time in Z2 ·
pace CV ≤{max_cv:.0%} · ≤{max_elev} ft/mi elevation · Z2 = {z2lo}–{z2hi} bpm ·
{n_steady}/{n_runs} runs eligible · dew point via Open-Meteo</footer>
</body></html>"""


def card(label, value, delta=""):
    color = "#d9534f" if str(delta).startswith("+") else "#2e8b57"
    d = f'<div class="delta" style="color:{color}">{delta}</div>' if delta else ""
    return (f'<div class="card"><div class="label">{label}</div>'
            f'<div class="value">{value}</div>{d}</div>')


def div(fig):
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False})


def efficiency_fig(steady):
    fig = go.Figure()
    scatter_bands = BANDS + ["unknown"]
    for band in scatter_bands:  # traces 0-3
        pts = steady[steady["dew_band"] == band]
        fig.add_trace(go.Scatter(
            x=pts["date_dt"], y=pts["pace_at_ref"], mode="markers", name=band,
            marker=dict(color=BAND_COLORS[band], size=7, opacity=0.75),
            customdata=np.stack([pts["name"], pts["eff_avg_hr"].round(0),
                                 pts["eff_pace_min_mi"].map(fmt_pace),
                                 pts["distance_mi"].round(1)], axis=-1)
            if len(pts) else None,
            hovertemplate="%{customdata[0]}<br>%{x|%b %d %Y}<br>"
                          "actual %{customdata[2]}/mi @ %{customdata[1]} bpm · "
                          "%{customdata[3]} mi<extra>" + band + "</extra>"))
    # traces 4-11: (line, low-confidence markers) per selection
    selections = [("All", steady)] + [(b, steady[steady["dew_band"] == b])
                                      for b in BANDS]
    for name, subset in selections:
        t = rolling_fit(subset) if len(subset) else pd.DataFrame()
        lowc = t[~t["confident"]] if len(t) else t
        fig.add_trace(go.Scatter(
            x=t["date_dt"] if len(t) else [], y=t["pace"] if len(t) else [],
            mode="lines", name=f"{C.FIT_WINDOW_DAYS}-day fit",
            line=dict(color="#222222", width=3), visible=(name == "All")))
        fig.add_trace(go.Scatter(
            x=lowc["date_dt"] if len(lowc) else [],
            y=lowc["pace"] if len(lowc) else [],
            mode="markers", name="low confidence",
            marker=dict(color="#222222", symbol="circle-open"),
            visible=(name == "All")))

    buttons = []
    for i, (name, _) in enumerate(selections):
        vis_scatter = [True] * 4 if name == "All" else \
            [b == name for b in scatter_bands]
        vis_trend = [False] * 8
        vis_trend[2 * i] = vis_trend[2 * i + 1] = True
        buttons.append(dict(label=name, method="update",
                            args=[{"visible": vis_scatter + vis_trend}]))
    fig.update_layout(
        updatemenus=[dict(type="buttons", direction="right", buttons=buttons,
                          x=0, xanchor="left", y=1.18, yanchor="top")],
        height=460, margin=dict(t=40, l=50, r=10),
        legend=dict(orientation="h"))
    fig.update_yaxes(autorange="reversed", title="min/mi (lower = faster)")
    return fig


def decoupling_fig(long_steady):
    fig = go.Figure()
    good = long_steady["decoupling_pct"] <= 5
    fig.add_trace(go.Scatter(
        x=long_steady["date_dt"], y=long_steady["decoupling_pct"], mode="markers",
        marker=dict(color=np.where(long_steady["decoupling_pct"] < 0, "#2e8b57",
                    np.where(good, "#4c9be8", "#d9534f")), size=8),
        customdata=long_steady["name"], name="runs",
        hovertemplate="%{customdata}<br>%{x|%b %d %Y}: %{y:.1f}%<extra></extra>"))
    roll = long_steady.set_index("date_dt")["decoupling_pct"].rolling("56D").mean()
    fig.add_trace(go.Scatter(x=roll.index, y=roll.values, mode="lines",
                             name="8-wk avg", line=dict(color="#222222")))
    fig.add_hline(y=5, line_dash="dash", line_color="#d9534f",
                  annotation_text="5% — aerobic durability threshold")
    fig.add_hline(y=0, line_dash="dot", line_color="#2e8b57",
                  annotation_text="negative = HR fell relative to pace (good)")
    fig.update_layout(height=340, margin=dict(t=10, l=50, r=10),
                      yaxis_title="1st vs 2nd half efficiency drift %",
                      legend=dict(orientation="h"))
    return fig


def line_fig(x, y, color, ytitle, reversed_y=False, race_line=True):
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines", line=dict(color=color)))
    if race_line:
        fig.add_vline(x=pd.Timestamp(C.RACE_DATE).timestamp() * 1000,
                      line_dash="dash", annotation_text="race")
    if reversed_y:
        fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=300, margin=dict(t=10, l=50, r=10),
                      yaxis_title=ytitle)
    return fig


def main():
    SITE.mkdir(exist_ok=True)
    if not (C.DATA / "runs.parquet").exists():
        SITE.joinpath("index.html").write_text(
            "<h1>No data yet</h1><p>Run pull.py, compute.py, export_static.py.</p>")
        print("No data — wrote placeholder site/index.html")
        return

    runs = pd.read_parquet(C.DATA / "runs.parquet")
    runs["date_dt"] = pd.to_datetime(runs["date"])
    vo2 = pd.read_parquet(C.DATA / "vo2max.parquet")
    pred = pd.read_parquet(C.DATA / "race_predictions.parquet").dropna(
        subset=["time_10k_s"])
    daily = pd.read_parquet(C.DATA / "daily_health.parquet")
    zones = json.loads((C.DATA / "hr_zones.json").read_text())
    steady = runs[runs["steady_z2"]].copy()
    long_steady = steady[steady["eligible_time_s"] >= C.DECOUPLING_MIN_DURATION_S]

    now_pace, delta_str = headline_delta(rolling_fit(steady))
    latest_dec = long_steady.iloc[-1]["decoupling_pct"] if len(long_steady) else np.nan
    cur_vo2 = vo2.sort_values("date").iloc[-1]["vo2max"] if len(vo2) else np.nan
    days = (dt.date.fromisoformat(C.RACE_DATE) - dt.date.today()).days

    cards = "".join([
        card(f"Pace @ {C.REF_HR} bpm", f"{fmt_pace(now_pace)} /mi", delta_str or ""),
        card("Latest long-run decoupling",
             f"{latest_dec:+.1f}%" if not np.isnan(latest_dec) else "—"),
        card("VO₂max", f"{cur_vo2:.1f}" if not np.isnan(cur_vo2) else "—"),
        card("Days to 10K", days, C.RACE_DATE),
    ])

    body = [f"<h2>Predicted pace at {C.REF_HR} bpm — steady Z2 runs</h2>",
            div(efficiency_fig(steady)),
            '<p class="caption">Scatter = each steady run scaled to the reference '
            "HR by its own efficiency factor; line = pace-vs-HR regression over a "
            f"trailing {C.FIT_WINDOW_DAYS}-day window. Buttons filter to one dew "
            "point band so weather can't masquerade as fitness.</p>",
            "<h2>Aerobic decoupling (Pa:HR) — steady runs ≥ 40 min</h2>"]
    body.append(div(decoupling_fig(long_steady)) if len(long_steady)
                else "<p class='caption'>No steady runs ≥ 40 min yet.</p>")

    body.append("<h2>Garmin VO₂max & 10K race prediction</h2><div class='grid2'>")
    body.append(div(line_fig(pd.to_datetime(vo2["date"]), vo2["vo2max"],
                             "#4c9be8", "VO₂max")))
    body.append(div(line_fig(pd.to_datetime(pred["date"]), pred["time_10k_s"] / 60,
                             "#e8a13c", "predicted 10K (min)", reversed_y=True)))
    body.append("</div><h2>Context</h2><div class='grid3'>")

    wk = runs.set_index("date_dt")["distance_mi"].resample("W").sum()
    fw = go.Figure(go.Bar(x=wk.index, y=wk.values, marker_color="#4c9be8"))
    fw.update_layout(height=260, margin=dict(t=10, l=40, r=10),
                     yaxis_title="weekly mi")
    body.append(div(fw))

    zcols = [c for c in runs.columns if c.startswith("z") and c.endswith("_s")]
    zt = runs.set_index("date_dt")[zcols].resample("W").sum()
    share = zt.div(zt.sum(axis=1), axis=0) * 100
    fz = go.Figure()
    palette = ["#9ec9ef", "#4c9be8", "#2e8b57", "#e8a13c", "#d9534f"]
    for i, c in enumerate(zcols):
        fz.add_trace(go.Scatter(x=share.index, y=share[c], stackgroup="one",
                                name=f"Z{i+1}", line=dict(width=0),
                                fillcolor=palette[i % 5]))
    fz.update_layout(height=260, margin=dict(t=10, l=40, r=10), showlegend=False,
                     yaxis=dict(range=[0, 100], title="% run time by zone"))
    body.append(div(fz))

    dd = daily.copy()
    dd["date"] = pd.to_datetime(dd["date"])
    fh = go.Figure()
    if "rhr" in dd:
        fh.add_trace(go.Scatter(x=dd["date"],
                                y=dd["rhr"].rolling(7, min_periods=1).mean(),
                                name="RHR (7d)", line=dict(color="#d9534f")))
    if "hrv" in dd:
        fh.add_trace(go.Scatter(x=dd["date"],
                                y=dd["hrv"].rolling(7, min_periods=1).mean(),
                                name="HRV (7d)", line=dict(color="#2e8b57"),
                                yaxis="y2"))
    fh.update_layout(height=260, margin=dict(t=10, l=40, r=10),
                     yaxis=dict(title="RHR"),
                     yaxis2=dict(title="HRV", overlaying="y", side="right"),
                     legend=dict(orientation="h"))
    body.append(div(fh))
    body.append("</div>")

    z2lo, z2hi = C.effective_z2(zones)
    html = PAGE.format(cards=cards, body="\n".join(body),
                       generated=dt.date.today().isoformat(),
                       z2lo=z2lo, z2hi=z2hi,
                       max_cv=C.MAX_PACE_CV, max_elev=C.MAX_ELEV_GAIN_FT_PER_MI,
                       n_steady=len(steady), n_runs=len(runs))
    SITE.joinpath("index.html").write_text(html)
    print(f"Wrote site/index.html ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
