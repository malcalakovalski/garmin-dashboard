"""Central config: paths, race info, and steady-Z2 eligibility thresholds.

The thresholds here are the tuning surface for the whole dashboard — if the
EF pool looks polluted (or too empty), adjust here and re-run compute.py.
"""

from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
STREAMS = DATA / "streams"
TOKENSTORE = str(ROOT / ".garminconnect")  # gitignored

START_DATE = "2022-01-01"  # backfill horizon for first pull
RACE_DATE = "2026-10-31"   # 10K race day
REF_HR = 145               # headline reference HR (mid-Z2, confirmed)

# --- Steady-Z2 eligibility gates ---
WARMUP_DISCARD_S = 300           # drop first 5 min (HR lag)
MIN_DURATION_S = 25 * 60         # post-discard duration must still clear this
MIN_TIME_IN_Z2 = 0.80            # fraction of moving time inside Z2 band
MAX_PACE_CV = 0.08               # CV of 30s-smoothed pace
MAX_ELEV_GAIN_FT_PER_MI = 40     # terrain gate (exclude, don't adjust)
MIN_MOVING_SPEED_MPS = 1.0       # below this = standing / paused
DECOUPLING_MIN_DURATION_S = 40 * 60

# --- Rolling fit for predicted pace at REF_HR ---
FIT_WINDOW_DAYS = 28
FIT_MIN_RUNS = 5                 # fewer runs → fall back to mean, flag low confidence
FIT_MIN_HR_SPREAD = 5            # bpm spread needed for a meaningful slope

# --- Dew point bands (°F) ---
DEW_BANDS = [
    ("<55°F", -100.0, 55.0),
    ("55–65°F", 55.0, 65.0),
    ("65°F+", 65.0, 200.0),
]


def dew_band(dew_f):
    if dew_f is None:
        return "unknown"
    for name, lo, hi in DEW_BANDS:
        if lo <= dew_f < hi:
            return name
    return "unknown"
