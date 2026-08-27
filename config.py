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

# Garmin's configured zones are factory defaults (Z2 119–138 @ max 201) and
# don't match actual training (easy-run cluster 140–155 bpm) — override here.
# Set to None to use the Garmin-configured zones from data/hr_zones.json.
Z2_OVERRIDE = (135, 152)

# --- Steady aerobic-run eligibility gates ---
# EF pool = easy aerobic runs. Named workouts are excluded by keyword (Runna
# names carry intent: tempo 161bpm/12%CV vs easy 149bpm/6%CV — cleaner signal
# than HR alone); the HR band is the backstop for unnamed/pre-plan runs.
EASY_HR_BAND = (135, 158)        # avg HR and most time must sit here
WORKOUT_NAME_KEYWORDS = ("interval", "tempo", "speed", "track", "race",
                         "walk run")
WARMUP_DISCARD_S = 300           # drop first 5 min (HR lag)
MIN_DURATION_S = 20 * 60         # post-discard duration must still clear this
MIN_TIME_IN_BAND = 0.60          # fraction of moving time inside EASY_HR_BAND
MAX_PACE_CV = 0.12               # CV of 30s-smoothed pace (GPS noise is
                                 # proportionally larger at ~13 min/mi paces)
MAX_ELEV_GAIN_FT_PER_MI = 50     # terrain gate (routes median 32 ft/mi)
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


def effective_z2(zones: dict):
    """(z2_low, z2_high): the manual override if set, else Garmin's zones."""
    return Z2_OVERRIDE or (zones["z2_low"], zones["z2_high"])


def effective_floors(zones: dict):
    """Zone floors for the time-in-zone panel, with Z2 edges overridden."""
    f = list(zones["floors"])
    if Z2_OVERRIDE:
        f[1], f[2] = Z2_OVERRIDE[0], Z2_OVERRIDE[1] + 1
    return f


def dew_band(dew_f):
    if dew_f is None:
        return "unknown"
    for name, lo, hi in DEW_BANDS:
        if lo <= dew_f < hi:
            return name
    return "unknown"
