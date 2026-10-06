"""V4.2.7 persistent-trend consensus + independent entry model."""

import os

V427_SCAN_CADENCE_HOURS = int(os.getenv("V427_SCAN_CADENCE_HOURS", "4"))
V427_EMBARGO_HOURS = int(os.getenv("V427_EMBARGO_HOURS", "32"))
V427_INITIAL_TRAIN_FRACTION = float(os.getenv("V427_INITIAL_TRAIN_FRACTION", "0.40"))
V427_OOS_FOLDS = int(os.getenv("V427_OOS_FOLDS", "4"))
V427_MIN_TRAIN_ROWS = int(os.getenv("V427_MIN_TRAIN_ROWS", "500"))

V427_MAX_ITER = int(os.getenv("V427_MAX_ITER", "180"))
V427_LEARNING_RATE = float(os.getenv("V427_LEARNING_RATE", "0.04"))
V427_MAX_LEAF_NODES = int(os.getenv("V427_MAX_LEAF_NODES", "15"))
V427_MIN_SAMPLES_LEAF = int(os.getenv("V427_MIN_SAMPLES_LEAF", "70"))
V427_L2 = float(os.getenv("V427_L2", "2.0"))

V427_PRIORITY_TOP_PCT = float(os.getenv("V427_PRIORITY_TOP_PCT", "0.10"))
V427_PERSISTENT_TOP_PCT = float(os.getenv("V427_PERSISTENT_TOP_PCT", "0.20"))
V427_MAX_REVERSAL_PROB = float(os.getenv("V427_MAX_REVERSAL_PROB", "0.55"))

V427_ZONE_WAIT_MAX_ATR = float(os.getenv("V427_ZONE_WAIT_MAX_ATR", "1.50"))
V427_MIN_SUPPORT_ROOM_R = float(os.getenv("V427_MIN_SUPPORT_ROOM_R", "2.20"))
V427_MIN_ZONE_FILL_EDGE = float(os.getenv("V427_MIN_ZONE_FILL_EDGE", "0.00"))
V427_MIN_2R_EDGE = float(os.getenv("V427_MIN_2R_EDGE", "0.00"))

# Reversal penalty exponent applied after geometric trend consensus.
V427_REVERSAL_PENALTY_POWER = float(os.getenv("V427_REVERSAL_PENALTY_POWER", "0.50"))
