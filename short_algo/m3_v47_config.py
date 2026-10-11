"""M3 V4.7 - diagnostic-only failure attribution on the exact V4.6 OOS window."""
M3_V47_PERIOD_START="2026-08-06T00:00:00+00:00"
M3_V47_PERIOD_END="2026-10-05T00:00:00+00:00"
M3_V47_FUTURE_END="2026-10-07T00:00:00+00:00"
M3_V47_BLOCK_DAYS=20
M3_V47_BLOCK_COUNT=3

# Replication gate: V4.7 must reproduce the exact V4.6 baseline sample.
M3_V47_EXPECTED_ENTRIES=60
M3_V47_EXPECTED_BLOCK_ENTRIES=[15,25,20]
M3_V47_EXPECTED_EXPECTANCY_R=-0.16020
M3_V47_EXPECTED_TOTAL_R=-9.61217
M3_V47_REPLICATION_TOL=1e-5

# Diagnostic bins are frozen before the V4.7 run. They are descriptive only.
M3_V47_NUMERIC_BINS={
    "impulse_atr":[-1e9,2.5,3.5,1e9],
    "pullback_retrace":[-1e9,0.20,0.30,0.40,1e9],
    "retest_penetration_atr15":[-1e9,0.10,0.25,1e9],
    "retest_volume_vs_displacement":[-1e9,0.50,1.00,1e9],
    "risk_pct":[-1e9,2.0,3.0,1e9],
    "distance_to_ema20_atr1h":[-1e9,-2.0,-1.0,0.0,1e9],
    "distance_to_ema50_atr1h":[-1e9,-3.0,-1.5,0.0,1e9],
    "coin_return_24h_pct":[-1e9,-10.0,-7.5,-5.0,1e9],
    "relative_weakness_24h_pct":[-1e9,-10.0,-7.5,-5.0,1e9],
    "volume_expansion_1h":[-1e9,0.8,1.2,2.0,1e9],
}

M3_V47_MIN_BUCKET_ENTRIES=8
M3_V47_FAST_SL_MINUTES=120
M3_V47_MEDIUM_SL_MINUTES=360
M3_V47_LOW_MFE_R=0.50
