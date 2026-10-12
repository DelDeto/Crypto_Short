"""M3 V4.9.1 - prospective-replay integrity for V4.8's single H1 winner."""

# The earlier Oct 05-10 sample was replayed AFTER hypothesis development,
# and must never count toward a genuinely prospective confirmation.
# V4.9 rule/workflow code was committed at 2026-10-12 03:22 UTC.
M3_V49_FORWARD_START="2026-10-12T04:00:00+00:00"
M3_V49_FREEZE_COMMIT="bec5be29a31abce8897554ef46aad3240d848e0f"
M3_V49_EVIDENCE_CLASS="PROSPECTIVE_REPLAY_NOT_REALTIME_SIGNAL_CAPTURE"

# Frozen from V4.7 -> validated in V4.8. Never retune in V4.9.
M3_V49_SHALLOW_RETEST_MAX_ATR15=0.10

# Sequential readiness gate. Passing remains shadow-only.
M3_V49_MIN_FORWARD_DAYS=14
M3_V49_MIN_H1_ENTRIES=20
M3_V49_MIN_ACTIVE_BLOCKS=2
M3_V49_MIN_POSITIVE_BLOCK_FRACTION=0.60
M3_V49_BLOCK_DAYS=7
M3_V49_EXIT_LOOKAHEAD_DAYS=2
