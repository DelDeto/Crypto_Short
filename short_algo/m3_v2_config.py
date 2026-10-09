"""M3 V2 — Clean 3% entry research configuration."""
import os

M3_V2_DAYS = int(os.getenv("M3_V2_DAYS", "60"))
M3_V2_COOLDOWN_HOURS = int(os.getenv("M3_V2_COOLDOWN_HOURS", "6"))
M3_V2_DISPLACEMENT_WINDOW_MIN = int(os.getenv("M3_V2_DISPLACEMENT_WINDOW_MIN", "180"))
M3_V2_RETEST_BARS = int(os.getenv("M3_V2_RETEST_BARS", "4"))
M3_V2_MIN_DISPLACEMENT_ATR15 = float(os.getenv("M3_V2_MIN_DISPLACEMENT_ATR15", "0.55"))
M3_V2_RETEST_BELOW_ATR15 = float(os.getenv("M3_V2_RETEST_BELOW_ATR15", "0.15"))
M3_V2_RETEST_ABOVE_ATR15 = float(os.getenv("M3_V2_RETEST_ABOVE_ATR15", "0.35"))
M3_V2_MAX_CHASE_ATR15 = float(os.getenv("M3_V2_MAX_CHASE_ATR15", "1.00"))
M3_V2_ROOM_GATE_PCT = float(os.getenv("M3_V2_ROOM_GATE_PCT", "3.50"))
M3_V2_MAX_TARGET_ATR = float(os.getenv("M3_V2_MAX_TARGET_ATR", "3.00"))
M3_V2_TARGET_PCT = float(os.getenv("M3_V2_TARGET_PCT", "3.00"))
