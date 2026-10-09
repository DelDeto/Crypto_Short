"""M3 V3.3 — retest entry optimization research config."""
import os

M3_V33_DAYS = int(os.getenv("M3_V33_DAYS", "60"))
M3_V33_COOLDOWN_HOURS = int(os.getenv("M3_V33_COOLDOWN_HOURS", "6"))
M3_V33_MIN_RETEST_QUALITY = int(os.getenv("M3_V33_MIN_RETEST_QUALITY", "3"))
M3_V33_MAX_TARGET_ATR = float(os.getenv("M3_V33_MAX_TARGET_ATR", "3.0"))
M3_V33_LIMIT_FILL_BARS = int(os.getenv("M3_V33_LIMIT_FILL_BARS", "2"))
M3_V33_MAX_REJECTION_CLOSE_DISTANCE_ATR15 = float(os.getenv("M3_V33_MAX_REJECTION_CLOSE_DISTANCE_ATR15", "0.35"))
M3_V33_TARGET_PCT = float(os.getenv("M3_V33_TARGET_PCT", "3.0"))
