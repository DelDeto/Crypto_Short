"""M3 V3.9 — entry quality + stop survivability research."""
import os

M3_V39_BLOCK_DAYS = int(os.getenv("M3_V39_BLOCK_DAYS", "30"))
M3_V39_BLOCK_COUNT = int(os.getenv("M3_V39_BLOCK_COUNT", "4"))
M3_V39_DEV_DAYS = int(os.getenv("M3_V39_DEV_DAYS", "60"))
M3_V39_OOS1_DAYS = int(os.getenv("M3_V39_OOS1_DAYS", "60"))
M3_V39_OOS2_DAYS = int(os.getenv("M3_V39_OOS2_DAYS", "60"))
M3_V39_V38_DAYS = int(os.getenv("M3_V39_V38_DAYS", "120"))
M3_V39_EMBARGO_DAYS = int(os.getenv("M3_V39_EMBARGO_DAYS", "2"))
M3_V39_COOLDOWN_HOURS = int(os.getenv("M3_V39_COOLDOWN_HOURS", "6"))
M3_V39_FILL_BARS = int(os.getenv("M3_V39_FILL_BARS", "2"))

# Frozen directional setup from V3.8.
M3_V39_RW24_MAX = -5.0

# Frozen entry variants. No tuning inside the run.
M3_V39_ENTRY_OFFSETS_ATR15 = {
    "poi_exact": 0.0,
    "poi_plus_0_15atr": 0.15,
    "poi_plus_0_25atr": 0.25,
}

# Stop-survivability diagnostics only.
M3_V39_STOP_CAPS_PCT = (0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0)
