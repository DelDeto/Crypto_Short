"""V4.4.11 M2 — Entry + Stop Study.

Signal/entry are frozen from V4.4.10/V4.4.9. This version studies execution
only: fixed ATR stop variants with the same causal entry, 2R/3R staged exits,
and 96h maximum hold.

No future path information is used to choose an entry or stop.
"""
import os

V4411_DAYS = int(os.getenv("V4411_DAYS", "60"))
V4411_FUTURE_BUFFER_DAYS = int(os.getenv("V4411_FUTURE_BUFFER_DAYS", "12"))
V4411_COOLDOWN_HOURS = int(os.getenv("V4411_COOLDOWN_HOURS", "96"))
V4411_HOLD_HOURS = int(os.getenv("V4411_HOLD_HOURS", "96"))

# Predeclared execution variants from V4.4.10 MAE study.
V4411_STOP_ATR_VARIANTS = (1.50, 1.75, 2.00)
V4411_TP1_R = float(os.getenv("V4411_TP1_R", "2.0"))
V4411_TP2_R = float(os.getenv("V4411_TP2_R", "3.0"))

# After TP1, protect remaining 50% at break-even from the following bar.
V4411_TP1_WEIGHT = float(os.getenv("V4411_TP1_WEIGHT", "0.50"))
V4411_TP2_WEIGHT = 1.0 - V4411_TP1_WEIGHT

# Research gate for a cohort/variant.
V4411_MIN_UNIQUE_FILLS = int(os.getenv("V4411_MIN_UNIQUE_FILLS", "30"))
V4411_MIN_PF = float(os.getenv("V4411_MIN_PF", "1.10"))
