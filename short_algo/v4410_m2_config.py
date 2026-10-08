"""V4.4.10 M2 — Entry Path Study / No-Stop Research.

The entry logic is frozen from V4.4.9 Confirmed Support Flip.
After entry there is NO stop-loss, NO take-profit and NO PnL gate.

The study observes how far price travels against and with the short thesis
before any exit rule is designed.
"""
import os

V4410_DAYS = int(os.getenv("V4410_DAYS", "60"))

# 7d support-flip watch + up to 12h entry confirmation + 7d path study.
V4410_FUTURE_BUFFER_DAYS = int(
    os.getenv("V4410_FUTURE_BUFFER_DAYS", "15")
)

V4410_PATH_HORIZONS_HOURS = (12, 24, 48, 72, 120, 168)
V4410_FAVORABLE_THRESHOLDS_ATR = (1.0, 2.0, 3.0, 4.0)
V4410_COOLDOWN_HOURS = int(os.getenv("V4410_COOLDOWN_HOURS", "96"))

# Diagnostic reclaim definition after entry. This never changes the path.
V4410_RECLAIM_BUFFER_ATR = float(
    os.getenv("V4410_RECLAIM_BUFFER_ATR", "0.10")
)
V4410_RECLAIM_CONFIRM_4H = int(
    os.getenv("V4410_RECLAIM_CONFIRM_4H", "2")
)
