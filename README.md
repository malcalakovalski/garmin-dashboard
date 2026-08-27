# Garmin Running Dashboard

One question: **am I getting better at running?** Every run is shown, broken
down by workout type (from Runna names); aerobic efficiency (pace at the same
heart rate), running form (cadence, L/R balance, stride, contact time,
vertical ratio, power), and durability each get a section. Clean numbers, no
modeled adjustments — confounds are excluded or surfaced, never corrected for.

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

## Steady aerobic-run eligibility (the efficiency section's pool)

The "Every run" view includes everything; only the efficiency section filters.
A run enters the efficiency pool if **all** gates pass (thresholds in
`config.py`):

| Gate | Rule | Kills |
|---|---|---|
| Outdoor GPS run | `type = running`, has start GPS | treadmill (bad pace, no weather) |
| Not a workout | name lacks interval/tempo/speed/track/race/walk-run | named workouts |
| Duration | ≥ 20 min after discarding first 5 min (HR lag) | short shakeouts |
| HR band | avg HR in 135–158 **and** ≥ 60% of moving time in band | hard efforts among untagged runs |
| Pace steadiness | CV of 30s-smoothed pace ≤ 12% | strides, fartleks, progressions |
| Terrain | elevation gain ≤ 50 ft/mi | hills (excluded, not grade-adjusted) |

## Metric definitions

- **Every run** — pace over time for all runs, colored by workout type parsed
  from run names; per-type 56-day rolling-median trends.
- **Easy pace at 145 bpm** — trailing 28-day pace-vs-HR regression across
  steady aerobic runs, evaluated at 145 bpm. Headline delta compares to
  8 weeks ago (day-to-day efficiency is noise; 8-week deltas are signal).
- **Running form** — cadence, ground-contact balance (50% line marked),
  stride length, ground contact time, vertical ratio, running power — as
  recorded by the watch, 28-day median lines.
- **Decoupling (Pa:HR)** — (EF first half − EF second half) / EF first half,
  steady runs ≥ 40 min. Under 5% = aerobically durable; negative = HR fell
  relative to pace (good).
- **Dew point** — Open-Meteo at the run's GPS start + hour; shown in hovers
  and the monthly report card as context (the watch sensor is not trusted).

Garmin's VO₂max and race predictions are deliberately not shown: they weight
high-HR running, which reads deliberate low-HR training as unfitness.
