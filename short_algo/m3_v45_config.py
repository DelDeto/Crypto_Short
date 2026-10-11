"""M3 V4.5 — regime attribution diagnostics only."""
M3_V45_COOLDOWN_HOURS=6

# Predeclared diagnostic bins. These do NOT alter eligibility.
M3_V45_NUMERIC_BINS={
    "market_return_24h_pct":[-1e9,-4.0,-1.5,1.5,1e9],
    "market_return_4h_pct":[-1e9,-1.5,-0.5,0.5,1e9],
    "relative_weakness_24h_pct":[-1e9,-10.0,-8.0,-5.0],
    "relative_weakness_4h_pct":[-1e9,-3.0,-1.5,0.0,1e9],
    "volume_expansion_1h":[-1e9,0.8,1.2,2.0,1e9],
    "breakdown_strength_atr1h":[-1e9,0.25,0.50,1.0,1e9],
    "distance_to_ema20_atr1h":[-1e9,-2.0,-1.0,0.0,1e9],
    "distance_to_ema50_atr1h":[-1e9,-3.0,-1.5,0.0,1e9],
}
M3_V45_MIN_BUCKET_ENTRIES=10
M3_V45_MIN_BUCKET_ACTIVE_BLOCKS=2
