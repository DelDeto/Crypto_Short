"""M3 V3.4 — setup-quality decomposition research config."""
import os

M3_V34_DAYS = int(os.getenv("M3_V34_DAYS", "60"))
M3_V34_COOLDOWN_HOURS = int(os.getenv("M3_V34_COOLDOWN_HOURS", "6"))

# Keep the same V3.3 core cohort and benchmark Entry B (POI limit).
M3_V34_MIN_RETEST_QUALITY = int(os.getenv("M3_V34_MIN_RETEST_QUALITY", "3"))
M3_V34_MAX_TARGET_ATR = float(os.getenv("M3_V34_MAX_TARGET_ATR", "3.0"))
M3_V34_LIMIT_FILL_BARS = int(os.getenv("M3_V34_LIMIT_FILL_BARS", "2"))

# Analysis-only thresholds. These are not promoted rules.
M3_V34_PENETRATION_SPLITS = (0.10, 0.15, 0.25)
M3_V34_VOLUME_SPLITS = (0.60, 0.80, 1.00, 1.25)
M3_V34_WICK_SPLITS = (0.15, 0.25, 0.35)
M3_V34_DISPLACEMENT_SPLITS = (0.70, 0.90, 1.20)
M3_V34_DISTANCE_SPLITS = (0.25, 0.50, 0.75)
