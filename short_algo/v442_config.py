"""V4.4.2 short-horizon research filters.

V4.4.2 intentionally reuses the causal V4.4/V4.4.1 execution replay and adds
only signal-time-safe quality tiers. Default validation horizon is 60 days.

M1_A = strict V4.4 Liquidity Reversal.
M1_B = scored V4.4.1 Liquidity Reversal with stronger pre-entry quality gates.
M2_OPT = EDGE-like Support Breakdown Continuation with regime/retest/location
quality filters aimed at preserving gross edge after costs.
"""
import os

V442_DAYS = int(os.getenv("V442_DAYS", "60"))
V442_COOLDOWN_HOURS = int(os.getenv("V442_COOLDOWN_HOURS", "96"))

# M1 B-grade quality gates (all known before fill/outcome).
V442_M1B_MIN_SCORE = int(os.getenv("V442_M1B_MIN_SCORE", "4"))
V442_M1B_MAX_COST_R = float(os.getenv("V442_M1B_MAX_COST_R", "0.20"))
V442_M1B_MIN_ROOM_R = float(os.getenv("V442_M1B_MIN_ROOM_R", "2.50"))

# M2 optimized EDGE-like continuation.
V442_M2_MIN_SCORE = int(os.getenv("V442_M2_MIN_SCORE", "4"))
V442_M2_MAX_ENTRY_BELOW_SUPPORT_ATR = float(
    os.getenv("V442_M2_MAX_ENTRY_BELOW_SUPPORT_ATR", "0.65")
)
V442_M2_MAX_COST_R = float(os.getenv("V442_M2_MAX_COST_R", "0.20"))
V442_M2_MIN_ROOM_R = float(os.getenv("V442_M2_MIN_ROOM_R", "2.50"))
V442_M2_MAX_BREAK_BODY_ATR = float(os.getenv("V442_M2_MAX_BREAK_BODY_ATR", "1.10"))
