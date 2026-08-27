"""Render the dashboard as one self-contained static page → site/index.html.

Reads data/ files only. Organized around one question: am I getting better
at running? Every-run view with type filters, easy-run efficiency, running
form (cadence / balance / stride / GCT / vertical ratio / power), durability.

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
TYPE_COLORS = {"easy": "#34d399", "long": "#818cf8", "tempo": "#fbbf24",
               "intervals": "#f87171", "walk-run": "#22d3ee",
               "race": "#f472b6", "untagged": "#64748b"}
TYPE_ORDER = ["easy", "long", "tempo", "intervals", "walk-run", "race",
              "untagged"]

LAYOUT = dict(
    template=None,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'Inter', ui-sans-serif, -apple-system, sans-serif",
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
<title>Am I getting better at running?</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
 :root {{ color-scheme: dark; }}
 body {{ font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
        background: #0b1120; color: #cbd5e1; max-width: 1150px;
        margin: 0 auto; padding: 24px 16px 40px; }}
 h1 {{ font-size: 1.45rem; color: #f1f5f9; margin: 0; letter-spacing: -.01em; }}
 .sub {{ color: #64748b; font-size: .85rem; margin: 4px 0 22px; }}
 h2 {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .09em;
      color: #7dd3fc; margin: 34px 0 2px; font-weight: 600; }}
 .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr));
          gap: 12px; }}
 .card {{ background: linear-gradient(160deg, #131c31, #0e1526);
         border: 1px solid #1e293b; border-radius: 14px; padding: 16px 18px;
         transition: border-color .15s; }}
 .card:hover {{ border-color: #334155; }}
 .card .label {{ font-size: .72rem; text-transform: uppercase;
                letter-spacing: .07em; color: #64748b; }}
 .card .value {{ font-size: 2.1rem; font-weight: 700; color: #f8fafc;
                line-height: 1.25; font-variant-numeric: tabular-nums; }}
 .card .value small {{ font-size: 1rem; color: #94a3b8; font-weight: 500; }}
 .card .delta {{ font-size: .82rem; margin-top: 2px; }}
 .cards.mini .card {{ padding: 12px 16px; border-radius: 12px; }}
 .cards.mini .value {{ font-size: 1.45rem; }}
 .up {{ color: #34d399; }} .down {{ color: #f87171; }} .flat {{ color: #94a3b8; }}
 .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
 @media (max-width: 900px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
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
<h1>Am I getting better at running?</h1>
<p class="sub">Every run, every type — updated {generated}</p>
<div class="cards">{cards}</div>
{body}
<footer>Run types come from workout names (Runna); pre-plan runs are
"untagged". Efficiency section uses steady aerobic runs only: outdoor GPS,
no named workouts, ≥{min_dur} min after 5-min warmup discard, avg HR
{lo}–{hi} bpm with ≥{min_band:.0%} of time in band, pace CV ≤{max_cv:.0%},
≤{max_elev} ft/mi elevation — {n_steady} of {n_runs} runs qualify. Dew point
(hover / report card) from Open-Meteo at each run's GPS start. Form metrics
as recorded by the watch. No modeled corrections anywhere. Paces in min/mi.</footer>
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


def type_trend(sub, col="pace_mi"):
    """56-day rolling median of a column for one run type, gap-broken."""
    t = (sub.set_index("date_dt")[col].rolling("56D", min_periods=3).median()
         .reset_index().rename(columns={col: "v"}))
    return gap_break(t.dropna(subset=["v"]))


def everyrun_fig(real):
    """All runs, pace over time, colored by type, filterable by type."""
    types = [t for t in TYPE_ORDER if (real["run_type"] == t).any()]
    fig = go.Figure()
    for t in types:  # scatter traces
        pts = real[real["run_type"] == t]
        fig.add_trace(go.Scatter(
            x=pts["date_dt"], y=pts["pace_mi"], mode="markers", name=t,
            marker=dict(color=TYPE_COLORS[t], size=8, opacity=0.85,
                        line=dict(width=1, color="rgba(15,23,42,.8)")),
            customdata=np.stack([pts["name"].fillna(""),
                                 pts["distance_mi"].round(1),
                                 pts["avg_hr"].fillna(0).round(0),
                                 pts["dew_point_f"].fillna(-99).round(0)],
                                axis=-1),
            hovertemplate="%{customdata[0]}<br>%{x|%b %d %Y} · "
                          "%{customdata[1]} mi · %{customdata[2]:.0f} bpm · "
                          "dew %{customdata[3]:.0f}°F<br>%{y:.2f} min/mi"
                          "<extra>" + t + "</extra>"))
    for t in types:  # matching trend traces
        tr = type_trend(real[real["run_type"] == t])
        fig.add_trace(go.Scatter(
            x=tr["date_dt"], y=tr["v"], mode="lines", connectgaps=False,
            line=dict(color=TYPE_COLORS[t], width=2), opacity=0.9,
            name=f"{t} trend", showlegend=False, hoverinfo="skip"))
    n = len(types)
    buttons = [dict(label="All", method="update",
                    args=[{"visible": [True] * (2 * n)}])]
    for i, t in enumerate(types):
        vis = [j == i for j in range(n)] * 2
        buttons.append(dict(label=t, method="update", args=[{"visible": vis}]))
    fig.update_layout(
        updatemenus=[dict(type="buttons", direction="right", buttons=buttons,
                          x=0, xanchor="left", y=1.16, yanchor="top",
                          bgcolor="#131c31", bordercolor="#1e293b",
                          font=dict(color=INK), active=0)],
        margin=dict(t=44))
    fig.update_yaxes(autorange="reversed", title="pace (min/mi)")
    return fig


def efficiency_fig(steady):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=steady["date_dt"], y=steady["pace_at_ref"], mode="markers",
        name="steady runs",
        marker=dict(color=GOOD, size=8, opacity=0.85,
                    line=dict(width=1, color="rgba(15,23,42,.8)")),
        customdata=np.stack([steady["name"].fillna(""),
                             steady["eff_avg_hr"].round(0),
                             steady["eff_pace_min_mi"].map(fmt_pace),
                             steady["dew_point_f"].fillna(-99).round(0)],
                            axis=-1),
        hovertemplate="%{customdata[0]}<br>%{x|%b %d %Y}<br>"
                      "actual %{customdata[2]}/mi @ %{customdata[1]} bpm · "
                      "dew %{customdata[3]:.0f}°F<extra></extra>"))
    t = rolling_fit(steady)
    if len(t):
        tb = gap_break(t)
        fig.add_trace(go.Scatter(x=tb["date_dt"], y=tb["pace"], mode="lines",
                                 name=f"{C.FIT_WINDOW_DAYS}-day trend",
                                 connectgaps=False,
                                 line=dict(color="#f1f5f9", width=2.5)))
        lowc = t[~t["confident"]]
        fig.add_trace(go.Scatter(x=lowc["date_dt"], y=lowc["pace"],
                                 mode="markers", name="low confidence",
                                 marker=dict(color="#f1f5f9",
                                             symbol="circle-open", size=7)))
    fig.update_yaxes(autorange="reversed",
                     title=f"pace at {C.REF_HR} bpm (min/mi)")
    fig.update_xaxes(range=[dt.date.today() - dt.timedelta(days=300),
                            dt.date.today() + dt.timedelta(days=10)])
    return fig


def beats_fig(steady):
    s = steady.copy()
    s["beats_per_mi"] = s["eff_avg_hr"] * s["eff_pace_min_mi"]
    fig = go.Figure(go.Scatter(
        x=s["date_dt"], y=s["beats_per_mi"], mode="markers",
        marker=dict(color=ACCENT, size=8, opacity=0.8,
                    line=dict(width=1, color="rgba(15,23,42,.8)")),
        customdata=s["name"],
        hovertemplate="%{customdata}<br>%{x|%b %d %Y}: %{y:.0f} beats/mi"
                      "<extra></extra>", name="steady runs"))
    roll = (s.set_index("date_dt")["beats_per_mi"].rolling("28D").median()
            .reset_index().rename(columns={"beats_per_mi": "v"}))
    roll = gap_break(roll)
    fig.add_trace(go.Scatter(x=roll["date_dt"], y=roll["v"], mode="lines",
                             connectgaps=False, name="28-day median",
                             line=dict(color="#f1f5f9", width=2)))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title="heartbeats per mile")
    fig.update_xaxes(range=[dt.date.today() - dt.timedelta(days=300),
                            dt.date.today() + dt.timedelta(days=10)])
    return fig


def form_fig(real, col, ytitle, hline=None, hline_note="", better=""):
    """Generic form-metric trend: dots colored by type + 28d rolling median."""
    pts = real.dropna(subset=[col])
    fig = go.Figure(go.Scatter(
        x=pts["date_dt"], y=pts[col], mode="markers",
        marker=dict(color=[TYPE_COLORS[t] for t in pts["run_type"]], size=6,
                    opacity=0.55),
        customdata=pts["name"].fillna(""),
        hovertemplate="%{customdata}<br>%{x|%b %d %Y}: %{y:.1f}"
                      "<extra></extra>", name=""))
    roll = (pts.set_index("date_dt")[col].rolling("28D", min_periods=3)
            .median().reset_index().rename(columns={col: "v"}))
    roll = gap_break(roll.dropna(subset=["v"]))
    fig.add_trace(go.Scatter(x=roll["date_dt"], y=roll["v"], mode="lines",
                             connectgaps=False,
                             line=dict(color="#f1f5f9", width=2), name="28d"))
    if hline is not None:
        fig.add_hline(y=hline, line_dash="dot", line_color=MUTED, opacity=0.8,
                      annotation_text=hline_note, annotation_font_color=MUTED)
    if better:
        fig.add_annotation(text=better, xref="paper", yref="paper", x=0.02,
                           y=0.04, showarrow=False,
                           font=dict(color=MUTED, size=11))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title=ytitle)
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
            .rolling("56D").mean().reset_index()
            .rename(columns={"decoupling_pct": "v"}))
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


def calendar_fig(runs):
    end = pd.Timestamp.today().normalize()
    start = (end - pd.Timedelta(days=364)) - pd.Timedelta(days=int(
        (end - pd.Timedelta(days=364)).dayofweek))
    days = pd.date_range(start, end)
    daily = runs.groupby(runs["date_dt"].dt.normalize())["distance_mi"].sum()
    grid = pd.DataFrame({"day": days})
    grid["mi"] = grid["day"].map(daily).fillna(0.0)
    grid["week"] = grid["day"] - pd.to_timedelta(grid["day"].dt.dayofweek, "D")
    grid["dow"] = grid["day"].dt.dayofweek
    z = grid.pivot(index="dow", columns="week", values="mi")
    text = grid.pivot(index="dow", columns="week", values="day").map(
        lambda d: d.strftime("%b %d") if pd.notna(d) else "")
    fig = go.Figure(go.Heatmap(
        z=z.values, x=z.columns, y=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        text=text.values, xgap=3, ygap=3, showscale=False,
        colorscale=[[0, "#131c31"], [0.01, "#131c31"], [0.15, "#164e63"],
                    [0.45, "#0e7490"], [0.75, "#22d3ee"], [1, "#a5f3fc"]],
        hovertemplate="%{text}: %{z:.1f} mi<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, tickformat="%b")
    return fig


def longrun_fig(runs):
    wk = runs.set_index("date_dt")["distance_mi"].resample("W").max().fillna(0)
    fig = go.Figure(go.Bar(x=wk.index, y=wk.values, marker_color="#818cf8",
                           marker_line_width=0,
                           hovertemplate="wk of %{x|%b %d}: %{y:.1f} mi"
                                         "<extra></extra>"))
    fig.add_hline(y=6.2, line_dash="dash", line_color=INK, opacity=0.7,
                  annotation_text="10K", annotation_font_color=INK)
    fig.add_vline(x=pd.Timestamp(C.RACE_DATE).timestamp() * 1000,
                  line_dash="dot", line_color=BAD, opacity=0.7,
                  annotation_text="race", annotation_font_color=BAD)
    fig.update_yaxes(title="longest run of the week (mi)")
    fig.update_xaxes(range=[dt.date.today() - dt.timedelta(days=300),
                            pd.Timestamp(C.RACE_DATE) + pd.Timedelta(days=10)])
    return fig


def bests_cards(runs, steady, long_steady, wk):
    def when(ts):
        return pd.Timestamp(ts).strftime("%b %d, %Y")
    out = []
    if len(steady):
        b = steady.loc[steady["pace_at_ref"].idxmin()]
        out.append(card(f"Best pace @ {C.REF_HR}", fmt_pace(b["pace_at_ref"]),
                        "/mi", when(b["date_dt"])))
    if len(long_steady):
        b = long_steady.loc[long_steady["decoupling_pct"].idxmin()]
        out.append(card("Best long-run decoupling",
                        f"{b['decoupling_pct']:+.1f}%", "", when(b["date_dt"])))
    if len(wk):
        out.append(card("Biggest week", f"{wk.max():.1f}", "mi",
                        "wk of " + when(wk.idxmax())))
    if len(runs):
        b = runs.loc[runs["distance_mi"].idxmax()]
        out.append(card("Longest run", f"{b['distance_mi']:.1f}", "mi",
                        when(b["date_dt"])))
    return "<div class='cards mini'>" + "".join(out) + "</div>"


def monthly_table(runs, steady):
    r = runs.set_index("date_dt")
    s = steady.set_index("date_dt")
    months = sorted(r.index.to_period("M").unique())[-12:]
    rows = []
    for m in months:
        rm = r[r.index.to_period("M") == m]
        sm = s[s.index.to_period("M") == m]
        med = sm["pace_at_ref"].median() if len(sm) else np.nan
        cad = rm["avg_cadence_spm"].median()
        dew = rm["dew_point_f"].median()
        rows.append(
            f"<tr><td>{m.strftime('%b %Y')}</td><td>{len(rm)}</td>"
            f"<td>{rm['distance_mi'].sum():.0f}</td>"
            f"<td>{fmt_pace(med)}</td>"
            f"<td>{cad:.0f}</td>" if pd.notna(cad) else
            f"<tr><td>{m.strftime('%b %Y')}</td><td>{len(rm)}</td>"
            f"<td>{rm['distance_mi'].sum():.0f}</td><td>{fmt_pace(med)}</td>"
            f"<td>—</td>")
        rows.append(f"<td>{dew:.0f}°F</td></tr>" if pd.notna(dew)
                    else "<td>—</td></tr>")
    return ("<table class='report'><tr><th>Month</th><th>Runs</th><th>Miles</th>"
            f"<th>Pace@{C.REF_HR}</th><th>Cadence</th><th>Median dew</th></tr>"
            + "".join(rows) + "</table>")


def main():
    SITE.mkdir(exist_ok=True)
    if not (C.DATA / "runs.parquet").exists():
        SITE.joinpath("index.html").write_text(
            "<h1>No data yet</h1><p>Run pull.py, compute.py, export_static.py.</p>")
        print("No data — wrote placeholder site/index.html")
        return

    runs = pd.read_parquet(C.DATA / "runs.parquet")
    runs["date_dt"] = pd.to_datetime(runs["date"])
    runs["pace_mi"] = 1609.344 / runs["avg_speed_mps"] / 60.0
    daily = pd.read_parquet(C.DATA / "daily_health.parquet")
    steady = runs[runs["steady_z2"]].copy()
    long_steady = steady[steady["eligible_time_s"] >= C.DECOUPLING_MIN_DURATION_S]
    # plausible outdoor-pace runs for charts (drops watch fumbles / bad GPS)
    real = runs[(runs["distance_mi"] >= 1) & runs["pace_mi"].between(4, 20)].copy()

    # headline numbers
    now_pace, delta_str = headline_delta(rolling_fit(steady))
    delta_cls = "flat"
    if delta_str:
        delta_cls = "down" if delta_str.startswith("+") else "up"

    wk = runs.set_index("date_dt")["distance_mi"].resample("W").sum()
    cur4, prev4 = wk.tail(4).mean(), wk.tail(8).head(4).mean()
    vol_delta = cur4 - prev4
    vol_cls = "up" if vol_delta >= 0 else "down"

    cad = real.dropna(subset=["avg_cadence_spm"]).set_index("date_dt")["avg_cadence_spm"]

    def trailing_mean(s, days=28):
        return s[s.index > s.index.max() - pd.Timedelta(days=days)].mean() \
            if len(s) else np.nan

    cad_now = trailing_mean(cad)
    cad_prev = trailing_mean(cad[cad.index <= cad.index.max()
                                 - pd.Timedelta(days=56)] if len(cad) else cad)
    cad_delta = ""
    cad_cls = "flat"
    if not np.isnan(cad_now) and not np.isnan(cad_prev):
        d = cad_now - cad_prev
        cad_delta = f"{d:+.0f} spm vs 8 wk ago"
        cad_cls = "up" if d >= 0 else "down"

    days = (dt.date.fromisoformat(C.RACE_DATE) - dt.date.today()).days

    cards = "".join([
        card(f"Easy pace @ {C.REF_HR} bpm", fmt_pace(now_pace), "/mi",
             delta_str or "", delta_cls),
        card("Weekly volume (4-wk avg)", f"{cur4:.0f}", "mi",
             f"{vol_delta:+.0f} mi vs prior 4 wk", vol_cls),
        card("Cadence (28d avg)", f"{cad_now:.0f}" if not np.isnan(cad_now)
             else "—", "spm", cad_delta, cad_cls),
        card("Days to 10K", days, "", C.RACE_DATE, "flat"),
    ])

    body = [
        "<h2>Every run</h2>",
        "<p class='caption'>All runs, colored by workout type. Filter to one "
        "type to see its own trend — getting better shows up as every band "
        "drifting down.</p>",
        div(everyrun_fig(real), 460),

        "<h2>Aerobic efficiency — easy runs at the same heart rate</h2>",
        "<p class='caption'>The cleanest fitness signal: steady aerobic runs "
        f"only, expressed as predicted pace at {C.REF_HR} bpm (left) and "
        "heartbeats per mile (right).</p>",
        "<div class='grid2'>",
        div(efficiency_fig(steady), 330),
        div(beats_fig(steady), 330),
        "</div>",

        "<h2>Running form</h2>",
        "<p class='caption'>As recorded by the watch, all runs, dots colored "
        "by type with a 28-day median line. Speed = cadence × stride length; "
        "contact time and vertical ratio typically fall as economy improves.</p>",
        "<div class='grid2'>",
        div(form_fig(real, "avg_cadence_spm", "cadence (spm)"), 300),
        div(form_fig(real, "avg_gct_balance", "ground contact balance (% left)",
                     hline=50, hline_note="perfect 50/50"), 300),
        div(form_fig(real, "avg_stride_len_cm", "stride length (cm)"), 300),
        div(form_fig(real, "avg_gct_ms", "ground contact time (ms)",
                     better="lower = snappier"), 300),
        div(form_fig(real, "avg_vert_ratio", "vertical ratio (%)",
                     better="lower = less bounce per meter"), 300),
        div(form_fig(real, "avg_power_w", "running power (W)"), 300),
        "</div>",

        "<h2>Durability toward race day</h2>",
        "<p class='caption'>Decoupling: does efficiency hold from first to "
        "second half of long steady runs? Under 5% = durable. Alongside: "
        "longest run per week vs the 10K distance.</p>",
        "<div class='grid2'>",
        div(decoupling_fig(long_steady), 330) if len(long_steady)
        else "<p class='caption'>No steady runs ≥ 40 min yet.</p>",
        div(longrun_fig(runs), 330),
        "</div>",

        "<h2>Personal bests</h2>",
        bests_cards(runs, steady, long_steady, wk),

        "<h2>Monthly report card</h2>", monthly_table(runs, steady),

        "<h2>Consistency — trailing year</h2>",
        div(calendar_fig(runs), 210),
    ]

    body.append("<h2>Context</h2><div class='grid2'>")
    fw = go.Figure(go.Bar(x=wk.index, y=wk.values, marker_color=ACCENT,
                          marker_line_width=0, name="weekly mi"))
    fw.update_yaxes(title="weekly miles")
    body.append(div(fw, 260))

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
