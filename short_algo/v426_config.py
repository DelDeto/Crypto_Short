"""V4.2.6 persistent-trend + 2R entry-zone configuration."""

import os

V426_SCAN_CADENCE_HOURS = int(os.getenv("V426_SCAN_CADENCE_HOURS", "4"))
V426_EMBARGO_HOURS = int(os.getenv("V426_EMBARGO_HOURS", "32"))
V426_INITIAL_TRAIN_FRACTION = float(os.getenv("V426_INITIAL_TRAIN_FRACTION", "0.40"))
V426_OOS_FOLDS = int(os.getenv("V426_OOS_FOLDS", "4"))
V426_MIN_TRAIN_ROWS = int(os.getenv("V426_MIN_TRAIN_ROWS", "500"))

V426_MAX_ITER = int(os.getenv("V426_MAX_ITER", "160"))
V426_LEARNING_RATE = float(os.getenv("V426_LEARNING_RATE", "0.05"))
V426_MAX_LEAF_NODES = int(os.getenv("V426_MAX_LEAF_NODES", "15"))
V426_MIN_SAMPLES_LEAF = int(os.getenv("V426_MIN_SAMPLES_LEAF", "60"))
V426_L2 = float(os.getenv("V426_L2", "1.5"))

V426_ZONE_WAIT_HOURS = int(os.getenv("V426_ZONE_WAIT_HOURS", "8"))
V426_ZONE_NEAR_ATR = float(os.getenv("V426_ZONE_NEAR_ATR", "0.75"))
V426_ZONE_WAIT_MAX_ATR = float(os.getenv("V426_ZONE_WAIT_MAX_ATR", "1.50"))
V426_STOP_BUFFER_ATR = float(os.getenv("V426_STOP_BUFFER_ATR", "0.18"))
V426_MIN_SUPPORT_ROOM_R = float(os.getenv("V426_MIN_SUPPORT_ROOM_R", "2.0"))

V426_PRIORITY_TOP_PCT = float(os.getenv("V426_PRIORITY_TOP_PCT", "0.10"))
V426_WATCH_TOP_PCT = float(os.getenv("V426_WATCH_TOP_PCT", "0.20"))
V426_MAX_REVERSAL_PROB = float(os.getenv("V426_MAX_REVERSAL_PROB", "0.55"))

V426_FIRST_MOVE_ATR = float(os.getenv("V426_FIRST_MOVE_ATR", "0.50"))
V426_FIRST_MOVE_WINDOW_HOURS = int(os.getenv("V426_FIRST_MOVE_WINDOW_HOURS", "24"))

# Composite quality weights. Trend persistence has the largest weight.
V426_W_PERSISTENT = float(os.getenv("V426_W_PERSISTENT", "0.45"))
V426_W_ZONE_2R = float(os.getenv("V426_W_ZONE_2R", "0.25"))
V426_W_FIRST = float(os.getenv("V426_W_FIRST", "0.10"))
V426_W_24H = float(os.getenv("V426_W_24H", "0.10"))
V426_W_NO_REVERSAL = float(os.getenv("V426_W_NO_REVERSAL", "0.10"))
