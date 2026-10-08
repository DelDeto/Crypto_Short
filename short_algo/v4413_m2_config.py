"""V4.4.13 M2 — Persistent cohort diagnostic study.

Execution is frozen from the only V4.4.12 candidate that passed all gates:
- route: PERSISTENT_NO_RECLAIM_LOWER_HIGHS
- stop: 1.75 ATR
- TP1: 2 ATR (50%)
- TP2: 3 ATR (50%)
- break-even protection after TP1
- max hold: 96h

This version does NOT add a new live filter. It studies pre-entry features
that separate winners from losers.
"""
import os

V4413_DAYS = int(os.getenv("V4413_DAYS", "60"))
V4413_COOLDOWN_HOURS = int(os.getenv("V4413_COOLDOWN_HOURS", "96"))
V4413_HOLD_HOURS = int(os.getenv("V4413_HOLD_HOURS", "96"))

V4413_STOP_ATR = 1.75
V4413_TP1_ATR = 2.0
V4413_TP2_ATR = 3.0
V4413_TP1_WEIGHT = 0.50
V4413_TP2_WEIGHT = 0.50

V4413_MIN_COHORT_FILLS = int(os.getenv("V4413_MIN_COHORT_FILLS", "15"))
