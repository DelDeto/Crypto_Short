"""M3 V4.8 - pre-registered structural-quality validation on an independent historical holdout."""
M3_V48_PERIOD_START="2025-04-07T00:00:00+00:00"
M3_V48_PERIOD_END="2025-08-05T00:00:00+00:00"
M3_V48_FUTURE_END="2025-08-07T00:00:00+00:00"
M3_V48_BLOCK_DAYS=30
M3_V48_BLOCK_COUNT=4

# Frozen directly from V4.7 diagnostics. Do not retune in V4.8.
M3_V48_SHALLOW_RETEST_MAX_ATR15=0.10
M3_V48_CONTAINED_RISK_MAX_PCT=2.0
M3_V48_COMPACT_PULLBACK_BARS=1

M3_V48_HYPOTHESES={
    "H0_BASELINE":{"description":"No structural-quality filter"},
    "H1_SHALLOW_RETEST":{"description":"retest_penetration_atr15 <= 0.10"},
    "H2_CONTAINED_RISK":{"description":"structural risk_pct <= 2.0"},
    "H3_COMPACT_PULLBACK":{"description":"pullback_bars == 1"},
    "H4_ALL_THREE":{"description":"H1 AND H2 AND H3"},
}

# Pre-registered validation gate. Passing means shadow-candidate only, never auto-live.
M3_V48_MIN_ENTRIES=15
M3_V48_REQUIRED_ACTIVE_BLOCKS=4
M3_V48_MIN_POSITIVE_BLOCKS=3
