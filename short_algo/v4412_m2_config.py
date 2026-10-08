"""V4.4.12 M2 — Decoupled ATR Stop/Target Study.

Signal/entry are frozen from V4.4.10/V4.4.9.
Stops are defined in ATR above entry.
Targets are independently defined in ATR below entry.

This removes the V4.4.11 confound where wider stops automatically pushed
2R/3R targets farther away.
"""
import os

V4412_DAYS = int(os.getenv("V4412_DAYS", "60"))
V4412_FUTURE_BUFFER_DAYS = int(os.getenv("V4412_FUTURE_BUFFER_DAYS", "12"))
V4412_COOLDOWN_HOURS = int(os.getenv("V4412_COOLDOWN_HOURS", "96"))
V4412_HOLD_HOURS = int(os.getenv("V4412_HOLD_HOURS", "96"))

# Predeclared from V4.4.10/11 path study. Not a grid search.
V4412_STOP_ATR_VARIANTS = (1.25, 1.50, 1.75, 2.00)
V4412_TP1_ATR = float(os.getenv("V4412_TP1_ATR", "2.0"))
V4412_TP2_ATR = float(os.getenv("V4412_TP2_ATR", "3.0"))

V4412_TP1_WEIGHT = float(os.getenv("V4412_TP1_WEIGHT", "0.50"))
V4412_TP2_WEIGHT = 1.0 - V4412_TP1_WEIGHT

V4412_MIN_UNIQUE_FILLS = int(os.getenv("V4412_MIN_UNIQUE_FILLS", "30"))
V4412_MIN_PF = float(os.getenv("V4412_MIN_PF", "1.10"))
