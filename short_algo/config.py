import os

BASE_URL = os.getenv("MEXC_BASE_URL", "https://contract.mexc.com")
QUOTE_COIN = "USDT"

FAST_INTERVAL = "1h"
FAST_HISTORY = int(os.getenv("FAST_HISTORY", "96"))
FAST_MIN_HISTORY = 60
FAST_WORKERS = int(os.getenv("FAST_WORKERS", "6"))

DEEP_LIMIT = int(os.getenv("DEEP_LIMIT", "70"))
DEEP_HISTORY_1H = int(os.getenv("DEEP_HISTORY_1H", "180"))
DEEP_HISTORY_4H = int(os.getenv("DEEP_HISTORY_4H", "180"))
DEEP_MIN_HISTORY = 90
DEEP_WORKERS = int(os.getenv("DEEP_WORKERS", "6"))

MIN_TURNOVER_USDT = float(os.getenv("MIN_TURNOVER_USDT", "500000"))
MAX_SPREAD_BPS = float(os.getenv("MAX_SPREAD_BPS", "50"))
MAX_ABS_24H_CHANGE_PCT = float(os.getenv("MAX_ABS_24H_CHANGE_PCT", "80"))

ENTRY_READY_SCORE = float(os.getenv("ENTRY_READY_SCORE", "80"))
DEVELOPING_SCORE = float(os.getenv("DEVELOPING_SCORE", "70"))
WATCH_SCORE = float(os.getenv("WATCH_SCORE", "60"))

MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.25"))
MAX_ATR_PCT = float(os.getenv("MAX_ATR_PCT", "12"))
MAX_ENTRY_DISTANCE_ATR = float(os.getenv("MAX_ENTRY_DISTANCE_ATR", "0.65"))
MIN_STOP_ATR = float(os.getenv("MIN_STOP_ATR", "0.8"))
MAX_STOP_PCT = float(os.getenv("MAX_STOP_PCT", "8.0"))

TP1_R = float(os.getenv("TP1_R", "2.0"))
TP2_R = float(os.getenv("TP2_R", "3.0"))
RUNNER_R = float(os.getenv("RUNNER_R", "5.0"))

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
TOP_REPORT = int(os.getenv("TOP_REPORT", "20"))


# V2 historical validation. Defaults are intentionally moderate for GitHub
# Actions; set BACKTEST_SYMBOL_LIMIT=0 to request all currently tradable symbols.
BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", "90"))
BACKTEST_SYMBOL_LIMIT = int(os.getenv("BACKTEST_SYMBOL_LIMIT", "80"))
BACKTEST_HORIZON_HOURS = int(os.getenv("BACKTEST_HORIZON_HOURS", "72"))
BACKTEST_COOLDOWN_HOURS = int(os.getenv("BACKTEST_COOLDOWN_HOURS", "12"))
BACKTEST_STEP_HOURS = int(os.getenv("BACKTEST_STEP_HOURS", "1"))
BACKTEST_MIN_SCORE = float(os.getenv("BACKTEST_MIN_SCORE", "60"))
BACKTEST_WARMUP_DAYS = int(os.getenv("BACKTEST_WARMUP_DAYS", "25"))

BACKTEST_SHARD_INDEX = int(os.getenv("BACKTEST_SHARD_INDEX", "0"))
BACKTEST_SHARD_COUNT = max(1, int(os.getenv("BACKTEST_SHARD_COUNT", "1")))

# V2.1 execution-cost assumptions. These are research assumptions, not claims
# about a specific exchange fee tier. Override them from workflow inputs/env.
BACKTEST_FEE_BPS_ROUND_TRIP = float(os.getenv("BACKTEST_FEE_BPS_ROUND_TRIP", "8"))
BACKTEST_SLIPPAGE_BPS_ROUND_TRIP = float(os.getenv("BACKTEST_SLIPPAGE_BPS_ROUND_TRIP", "6"))

# V2.2 research defaults.
V22_ENTRY_SCORE = float(os.getenv("V22_ENTRY_SCORE", "70"))
V22_MAX_PER_TIMESTAMP = int(os.getenv("V22_MAX_PER_TIMESTAMP", "3"))
V22_MAX_CONCURRENT = int(os.getenv("V22_MAX_CONCURRENT", "3"))
V22_PORTFOLIO_RISK_PCT = float(os.getenv("V22_PORTFOLIO_RISK_PCT", "0.5"))
V22_STARTING_EQUITY = float(os.getenv("V22_STARTING_EQUITY", "10000"))
V22_WALK_FORWARD_TRAIN_DAYS = int(os.getenv("V22_WALK_FORWARD_TRAIN_DAYS", "60"))
V22_WALK_FORWARD_TEST_DAYS = int(os.getenv("V22_WALK_FORWARD_TEST_DAYS", "30"))


# V3 multi-strategy research defaults. V3 is isolated from the live V1 gate.
V3_MAX_COST_R = float(os.getenv("V3_MAX_COST_R", "0.10"))
V3_MAX_STOP_PCT = float(os.getenv("V3_MAX_STOP_PCT", "6.0"))
V3_MIN_SUPPORT_ROOM_R = float(os.getenv("V3_MIN_SUPPORT_ROOM_R", "2.0"))
V3_MAX_PER_TIMESTAMP = int(os.getenv("V3_MAX_PER_TIMESTAMP", "3"))
V3_MAX_CONCURRENT = int(os.getenv("V3_MAX_CONCURRENT", "3"))
V3_MAX_PER_CLUSTER = int(os.getenv("V3_MAX_PER_CLUSTER", "1"))
V3_PORTFOLIO_RISK_PCT = float(os.getenv("V3_PORTFOLIO_RISK_PCT", "0.5"))
V3_STARTING_EQUITY = float(os.getenv("V3_STARTING_EQUITY", "10000"))
