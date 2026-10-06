"""Configuration for the V4 probability-driven research pipeline."""

import os

V4_TRAIN_DAYS = int(os.getenv("V4_TRAIN_DAYS", "180"))
V4_TEST_DAYS = int(os.getenv("V4_TEST_DAYS", "30"))
V4_FINAL_HOLDOUT_DAYS = int(os.getenv("V4_FINAL_HOLDOUT_DAYS", "60"))
V4_EMBARGO_HOURS = int(os.getenv("V4_EMBARGO_HOURS", "72"))
V4_MIN_TRAIN_SAMPLES = int(os.getenv("V4_MIN_TRAIN_SAMPLES", "250"))
V4_MIN_ENGINE_SAMPLES = int(os.getenv("V4_MIN_ENGINE_SAMPLES", "40"))
V4_MIN_REGIME_SAMPLES = int(os.getenv("V4_MIN_REGIME_SAMPLES", "20"))

V4_MIN_EXPECTED_R = float(os.getenv("V4_MIN_EXPECTED_R", "0.15"))
V4_MIN_PROBABILITY = float(os.getenv("V4_MIN_PROBABILITY", "0.35"))
V4_ENGINE_MIN_EXPECTANCY = float(os.getenv("V4_ENGINE_MIN_EXPECTANCY", "0.0"))
V4_ENGINE_MIN_PF = float(os.getenv("V4_ENGINE_MIN_PF", "1.0"))

V4_MAX_PER_TIMESTAMP = int(os.getenv("V4_MAX_PER_TIMESTAMP", "3"))
V4_MAX_CONCURRENT = int(os.getenv("V4_MAX_CONCURRENT", "3"))
V4_MAX_PER_CLUSTER = int(os.getenv("V4_MAX_PER_CLUSTER", "1"))
V4_PORTFOLIO_RISK_PCT = float(os.getenv("V4_PORTFOLIO_RISK_PCT", "0.5"))
V4_STARTING_EQUITY = float(os.getenv("V4_STARTING_EQUITY", "10000"))

V4_LOGISTIC_L2 = float(os.getenv("V4_LOGISTIC_L2", "0.15"))
V4_LOGISTIC_STEPS = int(os.getenv("V4_LOGISTIC_STEPS", "350"))
V4_LOGISTIC_LR = float(os.getenv("V4_LOGISTIC_LR", "0.05"))
