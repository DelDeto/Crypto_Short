"""V4.2.9 location-first Early Downtrend configuration."""

import os

V429_SCAN_CADENCE_HOURS = int(os.getenv("V429_SCAN_CADENCE_HOURS", "4"))
V429_EMBARGO_HOURS = int(os.getenv("V429_EMBARGO_HOURS", "32"))
V429_INITIAL_TRAIN_FRACTION = float(os.getenv("V429_INITIAL_TRAIN_FRACTION", "0.40"))
V429_OOS_FOLDS = int(os.getenv("V429_OOS_FOLDS", "4"))
V429_MIN_TRAIN_ROWS = int(os.getenv("V429_MIN_TRAIN_ROWS", "500"))

# Models are ranking/context only in V4.2.9, never hard entry gates.
V429_MODEL_WEIGHT = float(os.getenv("V429_MODEL_WEIGHT", "0.25"))
V429_RULE_WEIGHT = float(os.getenv("V429_RULE_WEIGHT", "0.75"))
V429_REVERSAL_PENALTY_POWER = float(os.getenv("V429_REVERSAL_PENALTY_POWER", "0.60"))

# Core location-first entry policy.
V429_MAX_BREAKDOWN_AGE_HOURS = int(os.getenv("V429_MAX_BREAKDOWN_AGE_HOURS", "8"))
V429_ZONE_WAIT_MAX_ATR = float(os.getenv("V429_ZONE_WAIT_MAX_ATR", "1.50"))
V429_MIN_SUPPORT_ROOM_R = float(os.getenv("V429_MIN_SUPPORT_ROOM_R", "2.20"))

# Diagnostics.
V429_FOLLOWTHROUGH_R = float(os.getenv("V429_FOLLOWTHROUGH_R", "0.50"))
V429_POST_SL_HOURS = int(os.getenv("V429_POST_SL_HOURS", "72"))
V429_REQUIRED_FUTURE_HOURS = int(os.getenv("V429_REQUIRED_FUTURE_HOURS", "96"))
