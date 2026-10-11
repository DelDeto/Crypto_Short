"""M3 V3.6 — regime + relative weakness diagnostics config."""
import os

M3_V36_DAYS = int(os.getenv("M3_V36_DAYS", "60"))
M3_V36_DEV_DAYS = int(os.getenv("M3_V36_DEV_DAYS", "60"))
M3_V36_EMBARGO_DAYS = int(os.getenv("M3_V36_EMBARGO_DAYS", "2"))
M3_V36_COOLDOWN_HOURS = int(os.getenv("M3_V36_COOLDOWN_HOURS", "6"))
M3_V36_LIMIT_FILL_BARS = int(os.getenv("M3_V36_LIMIT_FILL_BARS", "2"))

# Frozen V3.5 baseline: Candidate B only.
M3_V36_MIN_QUALITY = 5
M3_V36_MAX_TARGET_ATR = 3.0

# Diagnostic buckets only; these are not promoted rules.
M3_V36_RW4_SPLITS = (-3.0, -2.0, -1.0, 0.0)
M3_V36_RW24_SPLITS = (-8.0, -5.0, -3.0, 0.0)
M3_V36_EMA20_ATR_SPLITS = (-2.0, -1.0, -0.5, 0.0)
M3_V36_EMA50_ATR_SPLITS = (-3.0, -2.0, -1.0, 0.0)
M3_V36_BREAKDOWN_ATR_SPLITS = (0.25, 0.50, 0.75, 1.00)
M3_V36_VOLUME_EXPANSION_SPLITS = (1.0, 1.25, 1.50, 2.0)
