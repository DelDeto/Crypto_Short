"""M3 V3.7 — frozen context-rule OOS validation."""
import os

M3_V37_DAYS = int(os.getenv("M3_V37_DAYS", "60"))
M3_V37_DEV_DAYS = int(os.getenv("M3_V37_DEV_DAYS", "60"))
M3_V37_PRIOR_OOS_DAYS = int(os.getenv("M3_V37_PRIOR_OOS_DAYS", "60"))
M3_V37_EMBARGO_DAYS = int(os.getenv("M3_V37_EMBARGO_DAYS", "2"))
M3_V37_COOLDOWN_HOURS = int(os.getenv("M3_V37_COOLDOWN_HOURS", "6"))
M3_V37_LIMIT_FILL_BARS = int(os.getenv("M3_V37_LIMIT_FILL_BARS", "2"))

# Frozen base setup from V3.5/V3.6.
M3_V37_MIN_QUALITY = 5
M3_V37_MAX_TARGET_ATR = 3.0

# Frozen context candidates from V3.6.
M3_V37_RW24_MAX = -5.0
M3_V37_VOLUME_MIN = 2.0
