"""V4.2.4 scanner-first directional ranking configuration."""

import os

# Walk-forward research settings.
V424_EMBARGO_HOURS = int(os.getenv("V424_EMBARGO_HOURS", "24"))
V424_INITIAL_TRAIN_FRACTION = float(os.getenv("V424_INITIAL_TRAIN_FRACTION", "0.40"))
V424_OOS_FOLDS = int(os.getenv("V424_OOS_FOLDS", "4"))
V424_MIN_TRAIN_ROWS = int(os.getenv("V424_MIN_TRAIN_ROWS", "120"))

# Logistic model settings. Fixed before OOS evaluation.
V424_MODEL_STEPS = int(os.getenv("V424_MODEL_STEPS", "450"))
V424_MODEL_LR = float(os.getenv("V424_MODEL_LR", "0.05"))
V424_MODEL_L2 = float(os.getenv("V424_MODEL_L2", "0.08"))

# Combined ranking weights.
V424_WEIGHT_4H = float(os.getenv("V424_WEIGHT_4H", "0.45"))
V424_WEIGHT_12H = float(os.getenv("V424_WEIGHT_12H", "0.20"))
V424_WEIGHT_FIRST = float(os.getenv("V424_WEIGHT_FIRST", "0.35"))

# Scanner decisions. Ranking, not automatic execution.
V424_PRIORITY_TOP_PCT = float(os.getenv("V424_PRIORITY_TOP_PCT", "0.15"))
V424_WAIT_TOP_PCT = float(os.getenv("V424_WAIT_TOP_PCT", "0.30"))
V424_PRIORITY_MIN_PROB = float(os.getenv("V424_PRIORITY_MIN_PROB", "0.52"))
V424_WAIT_MIN_PROB = float(os.getenv("V424_WAIT_MIN_PROB", "0.50"))
V424_READY_ZONE_DISTANCE_ATR = float(os.getenv("V424_READY_ZONE_DISTANCE_ATR", "0.75"))

# Severe anti-bottom rule remains a separate guardrail.
V424_BOTTOM_LOW_DISTANCE_ATR = float(os.getenv("V424_BOTTOM_LOW_DISTANCE_ATR", "0.25"))
V424_BOTTOM_SUPPORT_DISTANCE_ATR = float(os.getenv("V424_BOTTOM_SUPPORT_DISTANCE_ATR", "0.50"))
V424_BOTTOM_EMA_DISTANCE_ATR = float(os.getenv("V424_BOTTOM_EMA_DISTANCE_ATR", "1.80"))
V424_BOTTOM_FAST_DROP_ATR = float(os.getenv("V424_BOTTOM_FAST_DROP_ATR", "1.50"))

# Reference levels only.
V424_REFERENCE_STOP_BUFFER_ATR = float(os.getenv("V424_REFERENCE_STOP_BUFFER_ATR", "0.18"))
V424_SLIPPAGE_BPS_REFERENCE = float(os.getenv("V424_SLIPPAGE_BPS_REFERENCE", "6"))

V424_FIRST_MOVE_ATR = float(os.getenv("V424_FIRST_MOVE_ATR", "0.50"))
V424_FIRST_MOVE_WINDOW_HOURS = int(os.getenv("V424_FIRST_MOVE_WINDOW_HOURS", "12"))
