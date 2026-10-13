"""Exploratory M5 event definitions -- NOT forward-preregistered hypotheses.

Any thresholds here are initial research candidates, not evidence of a
profitable strategy. Freeze a separate protocol BEFORE a later forward trial.
"""
EVENTS = {
    "E01": "Support Breakdown",
    "E02": "Downside Momentum Expansion",
    "E03": "Liquidity Sweep Reversal",
    "E04": "Overextension Mean Reversion",
    "E05": "Failed Support Reclaim",
    "E06": "Volume Climax Reversal",
    "E07": "Relative Weakness vs BTC",
    "E08": "Volatility Compression Breakdown",
}
INTERVAL_MINUTES = 15
WARMUP_BARS = 128
BARS_PER_REQUEST = 1200
MIN_CANDLE_COVERAGE = 0.85
MAX_API_ATTEMPTS = 6
MIN_REQUEST_SPACING_SECONDS = 1.10
MAX_CONTROLS = 3
RESEARCH_ONLY = True
