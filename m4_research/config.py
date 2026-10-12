"""M4 V0.1/V0.2 preregistered exploratory event-study parameters.

These are hypotheses, NOT calibrated or validated trading rules. Changing
parameters creates a new research version and invalidates comparisons.
"""
import os

API_BASE=os.getenv("M4_MEXC_BASE_URL","https://api.mexc.com").rstrip("/")
HISTORY_DAYS=int(os.getenv("M4_HISTORY_DAYS","60"))
WARMUP_HOURS=80
INTERVAL_SECONDS=3600
MAX_KLINE_BARS_PER_REQUEST=700  # Conservatively below MEXC's 2,000-point cap.
SHARD_COUNT=max(1,int(os.getenv("M4_SHARD_COUNT","8")))
SHARD_INDEX=int(os.getenv("M4_SHARD_INDEX","0"))
OUT_DIR=os.getenv("M4_OUTPUT_DIR","output/m4")
MAX_SYMBOLS=int(os.getenv("M4_MAX_SYMBOLS","0")) # 0 = entire eligible active futures universe
MAX_ERROR_RATE=float(os.getenv("M4_MAX_ERROR_RATE","0.20"))

# Immutable V0.2 candidate H1
RUNUP_24H_MIN_PCT=8.0
SWEEP_MIN_PCT=0.25
WICK_MIN_RATIO=0.35
REQUIRE_BEARISH_CLOSE=True
PREVIOUS_HIGH_HOURS=48
MIN_ASOF_QUOTE_TURNOVER_24H=300_000.0
SAME_SYMBOL_COOLDOWN_HOURS=48
HORIZONS_HOURS=(4,12,24,48)
MATCHED_CONTROLS_PER_EVENT=3
RESEARCH_ONLY=True

# No entry, TP, SL, live promotion, leverage, or Telegram in this version.
