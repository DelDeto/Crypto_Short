"""M3 V4.2 — frozen structural-policy OOS validation."""
import os

M3_V42_BLOCK_DAYS=int(os.getenv("M3_V42_BLOCK_DAYS","30"))
M3_V42_BLOCK_COUNT=int(os.getenv("M3_V42_BLOCK_COUNT","4"))
M3_V42_COOLDOWN_HOURS=int(os.getenv("M3_V42_COOLDOWN_HOURS","6"))

# Frozen from V4.1 selection.
M3_V42_POLICY_NAME="struct_floor_125atr_100pct"
M3_V42_TARGET_R=3.0
M3_V42_BUFFER_ATR15=0.50
M3_V42_MIN_ATR15=1.25
M3_V42_MIN_PCT=1.00
