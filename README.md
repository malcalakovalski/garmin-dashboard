# Garmin Aerobic Efficiency Dashboard

One question: **am I getting faster at the same heart rate?** Everything here
serves that. Clean numbers, no modeled adjustments — confounds (humidity,
terrain, workout contamination) are excluded or surfaced, never corrected for.

## Usage

```bash
source .venv/bin/activate
python pull.py            # interactive first time (Garmin login), then token-cached
python compute.py         # derive per-run metrics → data/runs.parquet
streamlit run dashboard.py
```

`pull.py` is incremental and read-only: re-running fetches only new activities,
streams, and weather. Data lives in `data/` (gitignored), tokens in
`.garminconnect/` (gitignored).

## Publishing (GitHub Pages)

GitHub Pages is static, so the Streamlit app itself isn't hosted — instead
`export_static.py` renders the same charts into a self-contained
`site/index.html` (dew-band filter works client-side). Publish flow:

```bash
python pull.py && python compute.py && python export_static.py
git add site && git commit -m "update dashboard" && git push
```

The `pages.yml` workflow deploys `site/` on every push to main. The page is
**public**: it exposes dates, paces, HR, VO₂max, and Garmin run names — but
never GPS coordinates (they're not exported).

## Steady-Z2 eligibility (the EF pool)

A run counts toward the efficiency trend only if **all** gates pass
(thresholds in `config.py`):

| Gate | Rule | Kills |
|---|---|---|
| Outdoor GPS run | `type = running`, has start GPS | treadmill (bad pace, no weather) |
| Not a race | Garmin event type ≠ race | races |
| Duration | ≥ 25 min after discarding first 5 min (HR lag) | short shakeouts |
| HR containment | avg HR in Z2 **and** ≥ 80% of moving time in Z2 | workouts averaging into Z2 |
| Pace steadiness | CV of 30s-smoothed pace ≤ 8% | strides, fartleks, progressions |
| Terrain | elevation gain ≤ 40 ft/mi | hills (excluded, not grade-adjusted) |

The sidebar gate report shows how many runs each gate excluded, so the filter
is visible rather than silent.

## Metric definitions

- **Predicted pace at 145 bpm** — trailing 28-day pace-vs-HR regression across
  steady runs, evaluated at 145 bpm. Scatter points are each run's own pace
  scaled to 145 by its efficiency factor. Headline delta compares to 8 weeks
  ago (day-to-day EF is noise; 8-week deltas are signal).
- **Dew point bands** — Open-Meteo archive at the run's GPS start + start hour
  (watch temperature sensor is not trusted). Filter the trend to one band to
  separate weather from fitness.
- **Decoupling (Pa:HR)** — (EF first half − EF second half) / EF first half,
  steady runs ≥ 40 min. Under 5% = aerobically durable; negative = HR fell
  relative to pace (good).
- **VO₂max / 10K prediction** — Garmin's values, trended to race day.
