"""M3 V4.1 — true structural invalidation + risk floor research."""
import os

M3_V41_BLOCK_DAYS=int(os.getenv("M3_V41_BLOCK_DAYS","30"))
M3_V41_BLOCK_COUNT=int(os.getenv("M3_V41_BLOCK_COUNT","4"))
M3_V41_COOLDOWN_HOURS=int(os.getenv("M3_V41_COOLDOWN_HOURS","6"))

# Frozen directional setup / entry from V3.8-V3.9.
M3_V41_RW24_MAX=-5.0
M3_V41_ENTRY_OFFSET_ATR15=0.25
M3_V41_FILL_BARS=2

# Structural anchor lookbacks, fixed before this run.
M3_V41_LOCAL_15M_LOOKBACK=8
M3_V41_REJECTION_1H_LOOKBACK=3

# Three predeclared structural-risk policies.
# stop = max(structural_anchor + buffer*ATR15,
#            entry + max(min_atr*ATR15, min_pct*entry))
M3_V41_POLICIES={
    "struct_floor_075atr_050pct":{"buffer_atr15":0.10,"min_atr15":0.75,"min_pct":0.50},
    "struct_floor_100atr_075pct":{"buffer_atr15":0.25,"min_atr15":1.00,"min_pct":0.75},
    "struct_floor_125atr_100pct":{"buffer_atr15":0.50,"min_atr15":1.25,"min_pct":1.00},
}
M3_V41_TARGET_R=(2.0,3.0)
