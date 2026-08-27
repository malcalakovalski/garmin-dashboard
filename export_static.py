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

INK = "#cbd5e1"
MUTED = "#64748b"
GOOD = "#34d399"
BAD = "#f87171"
ACCENT = "#38bdf8"
BAND_COLORS = {"<55°F": "#38bdf8", "55–65°F": "#fbbf24", "65°F+": "#f87171",
               "unknown": "#475569"}
BANDS = [b[0] for b in C.DEW_BANDS]

LAYOUT = dict(
    template=None,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="ui-sans-serif, -apple-system, 'Segoe UI', sans-serif",
              color=INK, size=12),
    margin=dict(t=16, l=52, r=16, b=36),
    hoverlabel=dict(bgcolor="#1e293b", bordercolor="#334155",
                    font=dict(color="#e2e8f0")),
    legend=dict(orientation="h", bgcolor="rgba(0,0,0,0)"),
)
AXIS = dict(gridcolor="rgba(148,163,184,0.12)", zerolinecolor="rgba(148,163,184,0.2)",
            linecolor="rgba(148,163,184,0.25)")

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aerobic Efficiency</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 :root {{ color-scheme: dark; }}
 body {{ font-family: ui-sans-serif, -apple-system, 'Segoe UI', sans-serif;
        background: #0b1120; color: #cbd5e1; max-width: 1150px;
        margin: 0 auto; padding: 24px 16px 40px; }}
 h1 {{ font-size: 1.45rem; color: #f1f5f9; margin: 0; letter-spacing: -.01em; }}
 .sub {{ color: #64748b; font-size: .85rem; margin: 4px 0 22px; }}
 h2 {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .09em;
      color: #7dd3fc; margin: 34px 0 2px; font-weight: 600; }}
 .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr));
          gap: 12px; }}
 .card {{ background: linear-gradient(160deg, #131c31, #0e1526);
         border: 1px solid #1e293b; border-radius: 14px; padding: 16px 18px; }}
 .card .label {{ font-size: .72rem; text-transform: uppercase;
                letter-spacing: .07em; color: #64748b; }}
 .card .value {{ font-size: 2.1rem; font-weight: 700; color: #f8fafc;
                line-height: 1.25; font-variant-numeric: tabular-nums; }}
 .card .value small {{ font-size: 1rem; color: #94a3b8; font-weight: 500; }}
 .card .delta {{ font-size: .82rem; margin-top: 2px; }}
 .up {{ color: #34d399; }} .down {{ color: #f87171; }} .flat {{ color: #94a3b8; }}
 .grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
 @media (max-width: 900px) {{ .grid3 {{ grid-template-columns: 1fr; }} }}
 .caption {{ font-size: .78rem; color: #64748b; margin: 2px 0 0; }}
 table.report {{ border-collapse: collapse; width: 100%; margin-top: 8px;
                font-size: .85rem; font-variant-numeric: tabular-nums; }}
 table.report th {{ text-align: right; color: #64748b; font-weight: 600;
                   font-size: .72rem; text-transform: uppercase;
                   letter-spacing: .05em; padding: 6px 10px;
                   border-bottom: 1px solid #1e293b; }}
 table.report td {{ text-align: right; padding: 6px 10px;
                   border-bottom: 1px solid #131c31; color: #cbd5e1; }}
 table.report th:first-child, table.report td:first-child {{ text-align: left; }}
 table.report tr:last-child td {{ color: #f1f5f9; font-weight: 600; }}
 footer {{ margin-top: 40px; font-size: .72rem; color: #475569;
          border-top: 1px solid #1e293b; padding-top: 12px; line-height: 1.6; }}
</style></head><body>
<h1>Am I gaining aerobic efficiency?</h1>
<p class="sub">Faster at the same heart rate, controlled for weather — updated {generated}</p>
<div class="cards">{cards}</div>
{body}
<footer>Steady aerobic-run gates: outdoor GPS · no races or named workouts
(interval/tempo/speed/track/walk-run) · ≥{min_dur} min after 5-min warmup discard ·
avg HR {lo}–{hi} bpm with ≥{min_band:.0%} of time in band · pace CV ≤{max_cv:.0%} ·
≤{max_elev} ft/mi elevation gain — {n_steady} of {n_runs} runs qualify.
Dew point from Open-Meteo at each run's GPS start and hour (watch sensor not
trusted). No modeled corrections anywhere: weather and terrain are excluded or
shown, never adjusted for. Paces in min/mi.</footer>
</body></html>"""


def card(label, value, unit="", delta="", cls="flat"):
    u = f" <small>{unit}</small>" if unit else ""
    d = f'<div class="delta {cls}">{delta}</div>' if delta else ""
    return (f'<div class="card"><div class="label">{label}</div>'
            f'<div class="value">{value}{u}</div>{d}</div>')


def div(fig, height):
    fig.update_layout(height=height, **LAYOUT)
    fig.update_xaxes(**AXIS)
    fig.update_yaxes(**AXIS)
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False, "responsive": True})


def gap_break(df, max_gap_days=45):
    """Insert null rows into a date-sorted frame so Plotly breaks the line
    across data gaps instead of drawing a misleading bridge."""
    if len(df) < 2:
        return df
    df = df.sort_values("date_dt").reset_index(drop=True)
    gaps = df["date_dt"].diff() > pd.Timedelta(days=max_gap_days)
    pieces = []
    for i in range(len(df)):
        if gaps.iloc[i]:
            pieces.append(pd.DataFrame({"date_dt": [pd.NaT]}))
        pieces.append(df.iloc[[i]])
    return pd.concat(pieces, ignore_index=True)


def efficiency_fig(steady):
    fig = go.Figure()
    scatter_bands = BANDS + ["unknown"]
    for band in scatter_bands:  # traces 0-3
        pts = steady[steady["dew_band"] == band]
        fig.add_trace(go.Scatter(
            x=pts["date_dt"], y=pts["pace_at_ref"], mode="markers",
            name=f"dew {band}",
            marker=dict(color=BAND_COLORS[band], size=8, opacity=0.85,
                        line=dict(width=1, color="rgba(15,23,42,.8)")),
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
        tb = gap_break(t) if len(t) else t
        fig.add_trace(go.Scatter(
            x=tb["date_dt"] if len(tb) else [], y=tb["pace"] if len(tb) else [],
            mode="lines", name=f"{C.FIT_WINDOW_DAYS}-day trend",
            line=dict(color="#f1f5f9", width=2.5),
            connectgaps=False, visible=(name == "All")))
        fig.add_trace(go.Scatter(
            x=lowc["date_dt"] if len(lowc) else [],
            y=lowc["pace"] if len(lowc) else [],
            mode="markers", name="low confidence (<5 runs in window)",
            marker=dict(color="#f1f5f9", symbol="circle-open", size=7),
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
                          x=0, xanchor="left", y=1.16, yanchor="top",
                          bgcolor="#131c31", bordercolor="#1e293b",
                          font=dict(color=INK),
                          active=0)],
        margin=dict(t=44))
    fig.update_yaxes(autorange="reversed", title="pace at %d bpm (min/mi)" % C.REF_HR)
    fig.update_xaxes(range=[dt.date.today() - dt.timedelta(days=300),
                            dt.date.today() + dt.timedelta(days=10)])
    return fig


def decoupling_fig(long_steady):
    fig = go.Figure()
    colors = np.where(long_steady["decoupling_pct"] < 0, GOOD,
                      np.where(long_steady["decoupling_pct"] <= 5, ACCENT, BAD))
    fig.add_trace(go.Scatter(
        x=long_steady["date_dt"], y=long_steady["decoupling_pct"], mode="markers",
        marker=dict(color=colors, size=9,
                    line=dict(width=1, color="rgba(15,23,42,.8)")),
        customdata=long_steady["name"], name="runs ≥40 min",
        hovertemplate="%{customdata}<br>%{x|%b %d %Y}: %{y:.1f}%<extra></extra>"))
    roll = (long_steady.set_index("date_dt")["decoupling_pct"]
            .rolling("56D").mean().reset_index().rename(columns={"decoupling_pct": "v"}))
    roll = gap_break(roll)
    fig.add_trace(go.Scatter(x=roll["date_dt"], y=roll["v"], mode="lines",
                             name="8-wk avg", connectgaps=False,
                             line=dict(color="#f1f5f9", width=2)))
    fig.add_hline(y=5, line_dash="dash", line_color=BAD, opacity=0.7,
                  annotation_text="5% durability threshold",
                  annotation_font_color=BAD)
    fig.add_hline(y=0, line_dash="dot", line_color=GOOD, opacity=0.7,
                  annotation_text="negative = HR fell vs pace (good)",
                  annotation_font_color=GOOD, annotation_position="bottom right")
    fig.update_yaxes(title="efficiency drift, 1st → 2nd half (%)")
    fig.update_xaxes(range=[dt.date.today() - dt.timedelta(days=300),
                            dt.date.today() + dt.timedelta(days=10)])
    return fig


def monthly_table(runs, steady):
    r = runs.set_index("date_dt")
    s = steady.set_index("date_dt")
    months = sorted(r.index.to_period("M").unique())[-12:]
    rows = []
    for m in months:
        rm = r[r.index.to_period("M") == m]
        sm = s[s.index.to_period("M") == m]
        med = sm["pace_at_ref"].median() if len(sm) else np.nan
        dew = rm["dew_point_f"].median()
        rows.append(f"<tr><td>{m.strftime('%b %Y')}</td>"
                    f"<td>{len(rm)}</td>"
                    f"<td>{rm['distance_mi'].sum():.0f}</td>"
                    f"<td>{len(sm)}</td>"
                    f"<td>{fmt_pace(med)}</td>"
                    f"<td>{dew:.0f}°F</td></tr>" if pd.notna(dew) else
                    f"<tr><td>{m.strftime('%b %Y')}</td><td>{len(rm)}</td>"
                    f"<td>{rm['distance_mi'].sum():.0f}</td><td>{len(sm)}</td>"
                    f"<td>{fmt_pace(med)}</td><td>—</td></tr>")
    return ("<table class='report'><tr><th>Month</th><th>Runs</th><th>Miles</th>"
            "<th>Steady</th><th>Pace@%d</th><th>Median dew</th></tr>"
            % C.REF_HR + "".join(rows) + "</table>")


def main():
    SITE.mkdir(exist_ok=True)
    if not (C.DATA / "runs.parquet").exists():
        SITE.joinpath("index.html").write_text(
            "<h1>No data yet</h1><p>Run pull.py, compute.py, export_static.py.</p>")
        print("No data — wrote placeholder site/index.html")
        return

    runs = pd.read_parquet(C.DATA / "runs.parquet")
    runs["date_dt"] = pd.to_datetime(runs["date"])
    daily = pd.read_parquet(C.DATA / "daily_health.parquet")
    steady = runs[runs["steady_z2"]].copy()
    long_steady = steady[steady["eligible_time_s"] >= C.DECOUPLING_MIN_DURATION_S]

    # headline numbers
    now_pace, delta_str = headline_delta(rolling_fit(steady))
    delta_cls = "flat"
    if delta_str:
        delta_cls = "down" if delta_str.startswith("+") else "up"

    recent_dec = long_steady.tail(3)["decoupling_pct"]
    dec_val = f"{recent_dec.median():+.1f}%" if len(recent_dec) else "—"
    dec_cls = "up" if len(recent_dec) and recent_dec.median() <= 5 else "down"
    dec_note = ("last %d long runs" % len(recent_dec)) if len(recent_dec) else ""

    wk = runs.set_index("date_dt")["distance_mi"].resample("W").sum()
    cur4, prev4 = wk.tail(4).mean(), wk.tail(8).head(4).mean()
    vol_delta = cur4 - prev4
    vol_cls = "up" if vol_delta >= 0 else "down"

    days = (dt.date.fromisoformat(C.RACE_DATE) - dt.date.today()).days

    cards = "".join([
        card(f"Pace @ {C.REF_HR} bpm", fmt_pace(now_pace), "/mi",
             delta_str or "", delta_cls),
        card("Long-run decoupling", dec_val, "", dec_note, dec_cls),
        card("Weekly volume (4-wk avg)", f"{cur4:.0f}", "mi",
             f"{vol_delta:+.0f} mi vs prior 4 wk", vol_cls),
        card("Days to 10K", days, "", C.RACE_DATE, "flat"),
    ])

    body = [
        f"<h2>Predicted pace at {C.REF_HR} bpm</h2>",
        "<p class='caption'>Steady aerobic runs only. Filter to one dew point "
        "band so seasonal weather can't masquerade as fitness.</p>",
        div(efficiency_fig(steady), 440),
        "<p class='caption'>Dots = each run scaled to the reference HR by its "
        "own efficiency factor. Line = pace-vs-HR regression over a trailing "
        f"{C.FIT_WINDOW_DAYS}-day window, evaluated at {C.REF_HR} bpm.</p>",

        "<h2>Aerobic decoupling</h2>",
        "<p class='caption'>Steady runs ≥40 min: does efficiency hold from "
        "first half to second half? Under 5% = aerobically durable.</p>",
    ]
    body.append(div(decoupling_fig(long_steady), 330) if len(long_steady)
                else "<p class='caption'>No steady runs ≥ 40 min yet.</p>")

    body += ["<h2>Monthly report card</h2>", monthly_table(runs, steady)]

    body.append("<h2>Context</h2><div class='grid3'>")
    fw = go.Figure(go.Bar(x=wk.index, y=wk.values, marker_color=ACCENT,
                          marker_line_width=0, name="weekly mi"))
    fw.update_yaxes(title="weekly miles")
    body.append(div(fw, 260))

    zcols = [c for c in runs.columns if c.startswith("z") and c.endswith("_s")]
    zt = runs.set_index("date_dt")[zcols].resample("W").sum()
    share = zt.div(zt.sum(axis=1), axis=0) * 100
    fz = go.Figure()
    palette = ["#1d4ed8", "#38bdf8", "#34d399", "#fbbf24", "#f87171"]
    for i, c in enumerate(zcols):
        fz.add_trace(go.Scatter(x=share.index, y=share[c], stackgroup="one",
                                name=f"Z{i+1}", line=dict(width=0),
                                fillcolor=palette[i % 5]))
    fz.update_layout(showlegend=False)
    fz.update_yaxes(range=[0, 100], title="% run time by HR zone")
    body.append(div(fz, 260))

    dd = daily.copy()
    dd["date"] = pd.to_datetime(dd["date"])
    fh = go.Figure()
    if "rhr" in dd:
        fh.add_trace(go.Scatter(x=dd["date"],
                                y=dd["rhr"].rolling(7, min_periods=1).mean(),
                                name="resting HR (7d)", line=dict(color=BAD)))
    if "hrv" in dd:
        fh.add_trace(go.Scatter(x=dd["date"],
                                y=dd["hrv"].rolling(7, min_periods=1).mean(),
                                name="HRV (7d)", line=dict(color=GOOD),
                                yaxis="y2"))
    fh.update_layout(yaxis=dict(title="RHR", **AXIS),
                     yaxis2=dict(title="HRV", overlaying="y", side="right",
                                 **AXIS))
    body.append(div(fh, 260))
    body.append("</div>")

    lo, hi = C.EASY_HR_BAND
    html = PAGE.format(cards=cards, body="\n".join(body),
                       generated=dt.date.today().strftime("%b %d, %Y"),
                       lo=lo, hi=hi, min_dur=C.MIN_DURATION_S // 60,
                       min_band=C.MIN_TIME_IN_BAND, max_cv=C.MAX_PACE_CV,
                       max_elev=C.MAX_ELEV_GAIN_FT_PER_MI,
                       n_steady=len(steady), n_runs=len(runs))
    SITE.joinpath("index.html").write_text(html)
    print(f"Wrote site/index.html ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
