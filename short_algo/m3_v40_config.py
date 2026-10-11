"""M3 V4.0 — structural stop + R-multiple diagnostic."""
import os

M3_V40_BLOCK_DAYS = int(os.getenv("M3_V40_BLOCK_DAYS", "30"))
M3_V40_BLOCK_COUNT = int(os.getenv("M3_V40_BLOCK_COUNT", "4"))
M3_V40_DEV_DAYS = int(os.getenv("M3_V40_DEV_DAYS", "60"))
M3_V40_OOS1_DAYS = int(os.getenv("M3_V40_OOS1_DAYS", "60"))
M3_V40_OOS2_DAYS = int(os.getenv("M3_V40_OOS2_DAYS", "60"))
M3_V40_V38_DAYS = int(os.getenv("M3_V40_V38_DAYS", "120"))
M3_V40_EMBARGO_DAYS = int(os.getenv("M3_V40_EMBARGO_DAYS", "2"))
M3_V40_COOLDOWN_HOURS = int(os.getenv("M3_V40_COOLDOWN_HOURS", "6"))

# Frozen from V3.8/V3.9.
M3_V40_RW24_MAX = -5.0
M3_V40_ENTRY_OFFSET_ATR15 = 0.25
M3_V40_FILL_BARS = 2

# Structural stop candidates.
M3_V40_STOP_BUFFERS_ATR15 = {
    "retest_high_plus_0_10atr": 0.10,
    "retest_high_plus_0_25atr": 0.25,
    "retest_high_plus_0_50atr": 0.50,
}
M3_V40_TARGET_R = (2.0, 3.0)
