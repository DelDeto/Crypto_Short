"""Pre-registered M4 H2 confirmation hypothesis; never optimize on 2026 Aug-Oct sample."""
SOURCE_RUN=38206513291
SOURCE_MANIFEST="m4event-ed877792e8b4f42b"
SOURCE_ARTIFACT="M4-V02-Event-Study-Final"
SHARD_COUNT=8
CONFIRM_WITHIN_HOURS=6

# H2 (NEW exploratory hypothesis):
# After the H1 failed-breakout bar has CLOSED:
# - Every subsequent 1h candle CLOSE must remain below the previous 48h high.
# - Within 1..6 complete 1h candles, the first candle closing BELOW the
#   original H1 sweep candle's LOW is the confirmation.
# - Outcomes are referenced to the NEXT hourly candle OPEN, never to original H1 entry.
# - Reclaim happens if ANY 1h CLOSE >= old high before confirmation.
# The hypothesis does NOT require a separate lower-high pivot.
NO_RECLAIM_CLOSE_GE_PREVIOUS_HIGH=True
CONFIRM_CLOSE_LT_SWEEP_LOW=True
OUTCOME_HOURS=(4,12,24,48)
MIN_MATCHED_EVENTS_DESCRIPTIVE=30
RESEARCH_ONLY=True
