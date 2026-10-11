"""M3 V4.3 — exit architecture development on frozen V4.2 risk model."""
import os

M3_V43_COOLDOWN_HOURS=int(os.getenv("M3_V43_COOLDOWN_HOURS","6"))

# Fixed-target exits, predeclared before this run.
M3_V43_FIXED_TARGETS=(1.5,2.0,2.5,3.0)

# Partial architecture: 50% at 1.5R, 50% at 3R, original SL unchanged.
M3_V43_PARTIAL_FIRST_R=1.5
M3_V43_PARTIAL_FINAL_R=3.0
M3_V43_PARTIAL_FIRST_FRACTION=0.50
