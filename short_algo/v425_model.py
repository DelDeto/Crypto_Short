"""Deterministic walk-forward logistic model for V4.2.5."""

import math

import numpy as np

from .v425_config import (
    V425_MODEL_L2,
    V425_MODEL_LR,
    V425_MODEL_STEPS,
)


FEATURE_NAMES = [
    "candidate_context_points",
    "return_1h_pct",
    "return_3h_pct",
    "return_4h_pct",
    "return_12h_pct",
    "return_24h_pct",
    "relative_1h_pct",
    "relative_3h_pct",
    "relative_4h_pct",
    "relative_24h_pct",
    "ema20_distance_atr",
    "range_position_12h",
    "range_position_24h",
    "range_position_48h",
    "distance_12h_low_atr",
    "distance_24h_low_atr",
    "distance_12h_high_atr",
    "support_distance_atr",
    "supply_distance_atr",
    "zone_distance_atr",
    "atr_pct_1h",
    "volume_ratio_1h",
    "s1_ema_bear",
    "s1_lower_high",
    "s1_lower_low",
    "s4_ema_bear",
    "s4_lower_high",
    "s4_lower_low",
    "s4_macro_bear",
    "breakdown_detected",
    "breakdown_retest",
    "breakdown_age_1h",
    "breakdown_distance_atr",
    "sweep_detected",
    "sweep_age_1h",
    "bearish_rejection",
    "continuation_quality",
    "continuation_ready",
    "break_departure_atr",
    "break_body_atr",
    "break_volume_ratio",
    "retest_touched",
    "retest_rejection",
    "reclaim_seen",
    "acceptance_bars",
    "rebound_from_break_low_atr",
    "anti_bottom_total",
    "squeeze_risk",
    "market_r4_pct",
    "market_r24_pct",
    "market_risk_on",
    "market_risk_off",
    "market_bull",
    "market_bear",
    "zone_supply_1h",
    "zone_supply_4h",
    "zone_broken_support",
    "zone_sweep_retest",
]


def _safe(value):
    try:
        out = float(value)
        return out if math.isfinite(out) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _raw_matrix(rows):
    return np.asarray(
        [[_safe(r.get(name)) for name in FEATURE_NAMES] for r in rows],
        dtype=float,
    )


def _sigmoid(z):
    z = np.clip(z, -25.0, 25.0)
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(rows, target_key):
    usable = [r for r in rows if r.get(target_key) is not None]
    if not usable:
        return {
            "type": "constant",
            "probability": 0.5,
            "target": target_key,
            "train_n": 0,
            "feature_names": FEATURE_NAMES,
        }

    y = np.asarray([
        1.0 if bool(r[target_key]) else 0.0
        for r in usable
    ])
    base = float(np.mean(y))

    if len(usable) < 30 or np.unique(y).size < 2:
        return {
            "type": "constant",
            "probability": base,
            "target": target_key,
            "train_n": len(usable),
            "feature_names": FEATURE_NAMES,
        }

    x = _raw_matrix(usable)
    med = np.nanmedian(x, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    inds = np.where(~np.isfinite(x))
    x[inds] = np.take(med, inds[1])

    mean = np.mean(x, axis=0)
    std = np.std(x, axis=0)
    std = np.where(std >= 1e-8, std, 1.0)
    z = (x - mean) / std

    n, p = z.shape
    w = np.zeros(p, dtype=float)
    b = float(np.log((base + 1e-5) / (1.0 - base + 1e-5)))

    positives = max(float(np.sum(y)), 1.0)
    negatives = max(float(n - np.sum(y)), 1.0)
    pos_weight = n / (2.0 * positives)
    neg_weight = n / (2.0 * negatives)
    sample_weight = np.where(y > 0.5, pos_weight, neg_weight)

    for step in range(int(V425_MODEL_STEPS)):
        pred = _sigmoid(z @ w + b)
        err = (pred - y) * sample_weight
        grad_w = (z.T @ err) / n + float(V425_MODEL_L2) * w
        grad_b = float(np.mean(err))
        step_lr = float(V425_MODEL_LR) / (1.0 + 0.002 * step)
        w -= step_lr * grad_w
        b -= step_lr * grad_b

    return {
        "type": "logistic",
        "target": target_key,
        "feature_names": FEATURE_NAMES,
        "train_n": n,
        "base_rate": round(base, 6),
        "median": med.tolist(),
        "mean": mean.tolist(),
        "std": std.tolist(),
        "coef": w.tolist(),
        "intercept": float(b),
    }


def predict_logistic(model, rows):
    if not rows:
        return []
    if model.get("type") == "constant":
        return [
            float(model.get("probability", 0.5))
            for _ in rows
        ]

    x = _raw_matrix(rows)
    med = np.asarray(model["median"], dtype=float)
    inds = np.where(~np.isfinite(x))
    x[inds] = np.take(med, inds[1])
    mean = np.asarray(model["mean"], dtype=float)
    std = np.asarray(model["std"], dtype=float)
    w = np.asarray(model["coef"], dtype=float)
    b = float(model["intercept"])
    z = (x - mean) / std
    return _sigmoid(z @ w + b).tolist()
