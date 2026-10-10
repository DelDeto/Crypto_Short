"""M3 V3.5 — frozen-rule temporal OOS validation config."""
import os

M3_V35_OOS_DAYS = int(os.getenv("M3_V35_OOS_DAYS", "60"))
M3_V35_DEV_DAYS = int(os.getenv("M3_V35_DEV_DAYS", "60"))
M3_V35_EMBARGO_DAYS = int(os.getenv("M3_V35_EMBARGO_DAYS", "2"))
M3_V35_COOLDOWN_HOURS = int(os.getenv("M3_V35_COOLDOWN_HOURS", "6"))
M3_V35_LIMIT_FILL_BARS = int(os.getenv("M3_V35_LIMIT_FILL_BARS", "2"))

# Frozen from V3.4. Do not tune during this OOS run.
M3_V35_CORE_MIN_QUALITY = 3
M3_V35_CORE_MAX_TARGET_ATR = 3.0

# Candidate A
M3_V35_A_MAX_PENETRATION_ATR15 = 0.10

# Candidate B
M3_V35_B_MIN_QUALITY = 5

# Candidate C
M3_V35_C_MAX_PENETRATION_ATR15 = 0.25
M3_V35_C_MAX_VOLUME_RATIO = 1.0
M3_V35_C_MIN_UPPER_WICK_RATIO = 0.25
M3_V35_C_REQUIRE_LOWER_HIGH = 1
