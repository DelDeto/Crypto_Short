"""V4.4.3 60-day research configuration.

The causal V4.4/V4.4.1 replay is unchanged. V4.4.3 fixes the strict M1
comparator, evaluates M1 on independent 96h episodes, and exposes the exact
M2 filter funnel before/alongside a balanced EDGE-like quality cohort.
"""
import os

V443_DAYS = int(os.getenv("V443_DAYS", "60"))
V443_COOLDOWN_HOURS = int(os.getenv("V443_COOLDOWN_HOURS", "96"))

V443_M1B_MIN_SCORE = int(os.getenv("V443_M1B_MIN_SCORE", "4"))
V443_M1B_MAX_COST_R = float(os.getenv("V443_M1B_MAX_COST_R", "0.20"))
V443_M1B_MIN_ROOM_R = float(os.getenv("V443_M1B_MIN_ROOM_R", "2.50"))

V443_M1BPLUS_MIN_SCORE = int(os.getenv("V443_M1BPLUS_MIN_SCORE", "4"))
V443_M1BPLUS_MAX_COST_R = float(os.getenv("V443_M1BPLUS_MAX_COST_R", "0.18"))
V443_M1BPLUS_MIN_ROOM_R = float(os.getenv("V443_M1BPLUS_MIN_ROOM_R", "3.00"))

V443_M2_MIN_SCORE = int(os.getenv("V443_M2_MIN_SCORE", "3"))
V443_M2_MAX_ENTRY_BELOW_SUPPORT_ATR = float(
    os.getenv("V443_M2_MAX_ENTRY_BELOW_SUPPORT_ATR", "0.90")
)
V443_M2_MAX_BREAK_BODY_ATR = float(os.getenv("V443_M2_MAX_BREAK_BODY_ATR", "1.30"))
V443_M2_MAX_COST_R = float(os.getenv("V443_M2_MAX_COST_R", "0.22"))
V443_M2_MIN_ROOM_R = float(os.getenv("V443_M2_MIN_ROOM_R", "2.50"))
V443_M2_MIN_ACCEPTANCE_BARS = int(os.getenv("V443_M2_MIN_ACCEPTANCE_BARS", "2"))
