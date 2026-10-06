"""Feature extraction for the V4 meta-label layer.

All values are constructed at the signal timestamp. Outcome fields are never
included in the feature vector.
"""

import math

from .indicators import return_pct, volume_ratio


ENGINES = (
    "EXTREME_PUMP_REVERSAL",
    "EXHAUSTION_REVERSAL",
    "BREAKDOWN_RETEST",
    "RELATIVE_WEAKNESS",
    "FAILED_BREAKOUT_SUPPLY_FADE",
)
RISK_STATES = ("RISK_ON", "NEUTRAL", "RISK_OFF", "UNKNOWN")
TREND_STATES = ("BULL", "RANGE", "BEAR", "UNKNOWN")
VOL_STATES = ("LOW_VOL", "NORMAL_VOL", "HIGH_VOL", "UNKNOWN")


BASE_FEATURES = (
    "v3_score",
    "projected_cost_r",
    "stop_pct",
    "support_room_r",
    "return_4h_pct",
    "return_12h_pct",
    "return_24h_pct",
    "relative_4h_pct",
    "relative_24h_pct",
    "volume_ratio_1h",
    "micro_score",
    "market_r4",
    "market_r24",
    "market_atr_pct",
    "coin_atr_pct",
)

FEATURE_NAMES = (
    list(BASE_FEATURES)
    + [f"engine__{x}" for x in ENGINES]
    + [f"risk__{x}" for x in RISK_STATES]
    + [f"trend__{x}" for x in TREND_STATES]
    + [f"vol__{x}" for x in VOL_STATES]
)


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else float(default)
    except (TypeError, ValueError):
        return float(default)


def build_v4_features(candidate, one, regime):
    micro = candidate.get("v3_micro") or {}
    engine = str(candidate.get("v3_engine") or "UNKNOWN")
    risk_state = str(regime.get("risk_state") or "UNKNOWN")
    trend_state = str(regime.get("trend_state") or "UNKNOWN")
    vol_state = str(regime.get("vol_state") or "UNKNOWN")

    close = one["close"].astype(float)
    row = {
        "v3_score": _finite(candidate.get("v3_score")),
        "projected_cost_r": _finite(candidate.get("v3_projected_cost_r")),
        "stop_pct": _finite(candidate.get("stop_pct")),
        "support_room_r": _finite(candidate.get("support_room_r")),
        "return_4h_pct": _finite(return_pct(close, 4)),
        "return_12h_pct": _finite(return_pct(close, 12)),
        "return_24h_pct": _finite(return_pct(close, 24)),
        "relative_4h_pct": _finite(candidate.get("v3_relative_4h_pct")),
        "relative_24h_pct": _finite(candidate.get("v3_relative_24h_pct")),
        "volume_ratio_1h": _finite(volume_ratio(one), 1.0),
        "micro_score": _finite(micro.get("score")),
        "market_r4": _finite(regime.get("market_r4")),
        "market_r24": _finite(regime.get("market_r24")),
        "market_atr_pct": _finite(regime.get("market_atr_pct")),
        "coin_atr_pct": _finite(regime.get("coin_atr_pct")),
    }

    for name in ENGINES:
        row[f"engine__{name}"] = 1.0 if engine == name else 0.0
    for name in RISK_STATES:
        row[f"risk__{name}"] = 1.0 if risk_state == name else 0.0
    for name in TREND_STATES:
        row[f"trend__{name}"] = 1.0 if trend_state == name else 0.0
    for name in VOL_STATES:
        row[f"vol__{name}"] = 1.0 if vol_state == name else 0.0

    return {name: _finite(row.get(name)) for name in FEATURE_NAMES}
