"""M3 V3.8 — frozen multi-window stability validation."""
import os

M3_V38_BLOCK_DAYS = int(os.getenv("M3_V38_BLOCK_DAYS", "30"))
M3_V38_BLOCK_COUNT = int(os.getenv("M3_V38_BLOCK_COUNT", "4"))
M3_V38_DEV_DAYS = int(os.getenv("M3_V38_DEV_DAYS", "60"))
M3_V38_OOS1_DAYS = int(os.getenv("M3_V38_OOS1_DAYS", "60"))
M3_V38_OOS2_DAYS = int(os.getenv("M3_V38_OOS2_DAYS", "60"))
M3_V38_EMBARGO_DAYS = int(os.getenv("M3_V38_EMBARGO_DAYS", "2"))
M3_V38_COOLDOWN_HOURS = int(os.getenv("M3_V38_COOLDOWN_HOURS", "6"))

# Frozen from V3.6/V3.7.
M3_V38_RW24_MAX = -5.0
M3_V38_VOLUME_MIN = 2.0
