"""M3 V3.2 — post-retest trigger refinement research config."""
import os

M3_V32_DAYS = int(os.getenv("M3_V32_DAYS", "60"))
M3_V32_COOLDOWN_HOURS = int(os.getenv("M3_V32_COOLDOWN_HOURS", "6"))

# V2.1-derived development cohort. These gates are intentionally frozen for
# this study and are not claimed as independent OOS validation.
M3_V32_MIN_RETEST_QUALITY = int(os.getenv("M3_V32_MIN_RETEST_QUALITY", "3"))
M3_V32_MAX_TARGET_ATR = float(os.getenv("M3_V32_MAX_TARGET_ATR", "3.0"))

# V3.2 execution refinement: wait for continuation after a failed retest
# instead of always benchmarking the immediate next-bar open.
M3_V32_TRIGGER_BARS = int(os.getenv("M3_V32_TRIGGER_BARS", "4"))
M3_V32_TRIGGER_CLOSE_BUFFER_ATR15 = float(os.getenv("M3_V32_TRIGGER_CLOSE_BUFFER_ATR15", "0.00"))
M3_V32_MAX_TRIGGER_CHASE_ATR15 = float(os.getenv("M3_V32_MAX_TRIGGER_CHASE_ATR15", "0.75"))

# Tighter structural-quality diagnostic cohort.
M3_V32_TIGHT_MAX_PENETRATION_ATR15 = float(os.getenv("M3_V32_TIGHT_MAX_PENETRATION_ATR15", "0.15"))
M3_V32_TIGHT_MIN_UPPER_WICK_RATIO = float(os.getenv("M3_V32_TIGHT_MIN_UPPER_WICK_RATIO", "0.25"))

M3_V32_TARGET_PCT = float(os.getenv("M3_V32_TARGET_PCT", "3.0"))
