"""V4.4.6 60-day Retest Window research.

M1-A/M1-B stay unchanged at their causal E0 entry.
M2 waits 1-3 hours after an important support break and looks for a failed
reclaim near the broken support. The model refuses to chase if price already
extended too far before the retest.

R1 = balanced retest window.
R2 = stricter retest window.
"""
import os

V446_SCAN_CADENCE_HOURS = int(os.getenv("V446_SCAN_CADENCE_HOURS", "4"))
V446_REQUIRED_FUTURE_HOURS = int(os.getenv("V446_REQUIRED_FUTURE_HOURS", "96"))
V446_COOLDOWN_HOURS = int(os.getenv("V446_COOLDOWN_HOURS", "96"))

V446_RETEST_START_BARS = int(os.getenv("V446_RETEST_START_BARS", "4"))   # 1h
V446_RETEST_END_BARS = int(os.getenv("V446_RETEST_END_BARS", "12"))     # 3h
V446_RETEST_TOUCH_ATR = float(os.getenv("V446_RETEST_TOUCH_ATR", "0.15"))
V446_HARD_RECLAIM_ATR = float(os.getenv("V446_HARD_RECLAIM_ATR", "0.25"))
V446_REJECTION_WICK_RATIO = float(os.getenv("V446_REJECTION_WICK_RATIO", "0.20"))

# R1 balanced.
V446_R1_MIN_ACCEPT_CLOSES = int(os.getenv("V446_R1_MIN_ACCEPT_CLOSES", "2"))
V446_R1_MAX_PRE_EXTENSION_ATR = float(
    os.getenv("V446_R1_MAX_PRE_EXTENSION_ATR", "1.25")
)
V446_R1_MAX_ENTRY_BELOW_ATR = float(
    os.getenv("V446_R1_MAX_ENTRY_BELOW_ATR", "0.30")
)

# R2 strict.
V446_R2_MIN_ACCEPT_CLOSES = int(os.getenv("V446_R2_MIN_ACCEPT_CLOSES", "3"))
V446_R2_MAX_PRE_EXTENSION_ATR = float(
    os.getenv("V446_R2_MAX_PRE_EXTENSION_ATR", "0.90")
)
V446_R2_MAX_ENTRY_BELOW_ATR = float(
    os.getenv("V446_R2_MAX_ENTRY_BELOW_ATR", "0.20")
)

# Execution / risk.
V446_STOP_BUFFER_ATR = float(os.getenv("V446_STOP_BUFFER_ATR", "0.12"))
V446_MIN_RISK_ATR = float(os.getenv("V446_MIN_RISK_ATR", "0.50"))
V446_MAX_RISK_ATR = float(os.getenv("V446_MAX_RISK_ATR", "1.60"))
V446_MAX_STOP_PCT = float(os.getenv("V446_MAX_STOP_PCT", "6.0"))
V446_MAX_COST_R = float(os.getenv("V446_MAX_COST_R", "0.25"))
V446_MIN_ROOM_R = float(os.getenv("V446_MIN_ROOM_R", "2.20"))
V446_TP1_R = float(os.getenv("V446_TP1_R", "2.00"))
