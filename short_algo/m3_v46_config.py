"""M3 V4.6 - frozen regime-hypothesis OOS validation."""
M3_V46_PERIOD_START="2026-08-06T00:00:00+00:00"
M3_V46_PERIOD_END="2026-10-05T00:00:00+00:00"
M3_V46_FUTURE_END="2026-10-07T00:00:00+00:00"
M3_V46_BLOCK_DAYS=20
M3_V46_BLOCK_COUNT=3

# Predeclared hypotheses from V4.5.1 attribution. Do not tune in V4.6.
M3_V46_HYPOTHESES={
    "H0_BASELINE":{"description":"No regime filter"},
    "H1_RISK_OFF":{"description":"market_state == RISK_OFF"},
    "H2_BEARISH_4H":{"description":"-1.5 < market_return_4h_pct <= -0.5","lo_exclusive":-1.5,"hi_inclusive":-0.5},
    "H3_DEEP_RISK_OFF":{"description":"market_return_24h_pct <= -4.0","max_24h_pct":-4.0},
}

# Frozen shadow-eligibility gate. This is not a live-promotion gate.
M3_V46_MIN_ENTRIES=20
M3_V46_REQUIRED_ACTIVE_BLOCKS=3
M3_V46_MIN_POSITIVE_BLOCKS=2
