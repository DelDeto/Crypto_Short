"""V4.4.9 M2 — Confirmed Support Flip.

Research-only refinement of V4.4.8.

Core change:
- the first failed reclaim is evidence only, not SHORT_READY;
- the broken 4H support must demonstrate a support->resistance flip through
  repeated failed reclaim / lower-high structure or persistent no-reclaim;
- major 4H demand never blocks entry; it is diagnostic / runner context only;
- tactical risk > 1.5 ATR is rejected because V4.4.8 showed the widest-stop
  cohort performed materially worse.

All decisions are causal and use only closed candles available at that time.
"""
import os

# Persistent support-flip confirmation.
V449_WATCH_DAYS = int(os.getenv("V449_WATCH_DAYS", "7"))
V449_MIN_FLIP_HOURS = int(os.getenv("V449_MIN_FLIP_HOURS", "8"))
V449_RECLAIM_BUFFER_ATR = float(os.getenv("V449_RECLAIM_BUFFER_ATR", "0.10"))
V449_RECLAIM_CONFIRM_4H = int(os.getenv("V449_RECLAIM_CONFIRM_4H", "2"))
V449_RETEST_TOUCH_ATR = float(os.getenv("V449_RETEST_TOUCH_ATR", "0.20"))
V449_REJECTION_WICK_RATIO = float(
    os.getenv("V449_REJECTION_WICK_RATIO", "0.20")
)

# Route A: repeated failed reclaim + lower-high.
V449_MIN_FAILED_RECLAIMS = int(os.getenv("V449_MIN_FAILED_RECLAIMS", "2"))
V449_MIN_RECLAIM_SEPARATION_4H = int(
    os.getenv("V449_MIN_RECLAIM_SEPARATION_4H", "1")
)
V449_LOWER_HIGH_BUFFER_ATR = float(
    os.getenv("V449_LOWER_HIGH_BUFFER_ATR", "0.05")
)
V449_PIVOT_LEFT = int(os.getenv("V449_PIVOT_LEFT", "1"))
V449_PIVOT_RIGHT = int(os.getenv("V449_PIVOT_RIGHT", "1"))

# Route B: persistent no-reclaim + lower highs.
V449_PERSIST_MIN_4H_BARS = int(os.getenv("V449_PERSIST_MIN_4H_BARS", "6"))
V449_PERSIST_WINDOW_4H = int(os.getenv("V449_PERSIST_WINDOW_4H", "6"))
V449_PERSIST_MIN_CLOSES_BELOW = int(
    os.getenv("V449_PERSIST_MIN_CLOSES_BELOW", "5")
)
V449_PERSIST_MIN_PIVOT_HIGHS = int(
    os.getenv("V449_PERSIST_MIN_PIVOT_HIGHS", "2")
)

# Entry and tactical risk.
V449_ENTRY_CONFIRM_HOURS = int(os.getenv("V449_ENTRY_CONFIRM_HOURS", "12"))
V449_MAX_ENTRY_BELOW_SUPPORT_ATR = float(
    os.getenv("V449_MAX_ENTRY_BELOW_SUPPORT_ATR", "2.50")
)
V449_STOP_BUFFER_ATR = float(os.getenv("V449_STOP_BUFFER_ATR", "0.12"))
V449_MIN_RISK_ATR = float(os.getenv("V449_MIN_RISK_ATR", "0.50"))
V449_MAX_RISK_ATR = float(os.getenv("V449_MAX_RISK_ATR", "1.50"))
V449_MAX_STOP_PCT = float(os.getenv("V449_MAX_STOP_PCT", "8.0"))
V449_MAX_COST_R = float(os.getenv("V449_MAX_COST_R", "0.25"))

# Risk ladder. Major demand is not a hard gate.
V449_HOLD_HOURS = int(os.getenv("V449_HOLD_HOURS", "96"))
V449_TP1_R = float(os.getenv("V449_TP1_R", "2.00"))
V449_TP2_R = float(os.getenv("V449_TP2_R", "4.00"))

# Major 4H demand diagnostics / runner only.
V449_MAJOR_LOOKBACK_4H = int(os.getenv("V449_MAJOR_LOOKBACK_4H", "360"))
V449_MAJOR_CLUSTER_ATR = float(os.getenv("V449_MAJOR_CLUSTER_ATR", "0.60"))
V449_MAJOR_MIN_SEPARATION_BARS = int(
    os.getenv("V449_MAJOR_MIN_SEPARATION_BARS", "4")
)
V449_MAJOR_DEPARTURE_ATR = float(
    os.getenv("V449_MAJOR_DEPARTURE_ATR", "2.00")
)
V449_MAJOR_WIDTH_ATR = float(os.getenv("V449_MAJOR_WIDTH_ATR", "0.80"))
V449_MAJOR_TARGET_BUFFER_ATR = float(
    os.getenv("V449_MAJOR_TARGET_BUFFER_ATR", "0.10")
)
