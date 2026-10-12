"""M3 V4.9 - forward shadow validation for the single V4.8 winner: shallow retest."""
M3_V49_FORWARD_START="2026-10-05T00:00:00+00:00"

# Frozen from V4.7 -> validated in V4.8. Never retune in V4.9.
M3_V49_SHALLOW_RETEST_MAX_ATR15=0.10

# Sequential readiness gate. Passing remains shadow-only.
M3_V49_MIN_FORWARD_DAYS=14
M3_V49_MIN_H1_ENTRIES=20
M3_V49_MIN_ACTIVE_BLOCKS=2
M3_V49_MIN_POSITIVE_BLOCK_FRACTION=0.60
M3_V49_BLOCK_DAYS=7
M3_V49_EXIT_LOOKAHEAD_DAYS=2
