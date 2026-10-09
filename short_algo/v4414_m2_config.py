"""V4.4.14 M2 — Causal watch-time gate validation.

Promotes exactly one V4.4.13 diagnostic finding into a real pre-entry rule:
the persistent support-flip setup must become ready between 24h and 48h
after the structural break.

Everything else remains frozen:
- route: PERSISTENT_NO_RECLAIM_LOWER_HIGHS
- stop: 1.75 ATR
- TP1: 2 ATR (50%)
- TP2: 3 ATR (50%)
- break-even on remainder after TP1
- max hold: 96h
"""
import os

V4414_DAYS = int(os.getenv("V4414_DAYS", "60"))
V4414_COOLDOWN_HOURS = int(os.getenv("V4414_COOLDOWN_HOURS", "96"))

V4414_MIN_WATCH_HOURS = float(os.getenv("V4414_MIN_WATCH_HOURS", "24"))
V4414_MAX_WATCH_HOURS = float(os.getenv("V4414_MAX_WATCH_HOURS", "48"))

V4414_STOP_ATR = 1.75
V4414_TP1_ATR = 2.0
V4414_TP2_ATR = 3.0

V4414_MIN_UNIQUE_FILLS = int(os.getenv("V4414_MIN_UNIQUE_FILLS", "15"))
V4414_MIN_PF = float(os.getenv("V4414_MIN_PF", "1.20"))
