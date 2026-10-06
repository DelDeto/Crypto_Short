"""Pure-numpy walk-forward meta-label model for V4.

V4 does not ask the model to discover entries from raw market data. The rule
engines generate candidates first; this layer estimates whether each candidate
is worth allocating risk to.
"""

import math

import numpy as np
import pandas as pd

from .v3_calibration import metrics
from .v4_config import (
    V4_EMBARGO_HOURS,
    V4_ENGINE_MIN_EXPECTANCY,
    V4_ENGINE_MIN_PF,
    V4_FINAL_HOLDOUT_DAYS,
    V4_LOGISTIC_L2,
    V4_LOGISTIC_LR,
    V4_LOGISTIC_STEPS,
    V4_MIN_ENGINE_SAMPLES,
    V4_MIN_EXPECTED_R,
    V4_MIN_PROBABILITY,
    V4_MIN_REGIME_SAMPLES,
    V4_MIN_TRAIN_SAMPLES,
    V4_TEST_DAYS,
    V4_TRAIN_DAYS,
)
from .v4_features import FEATURE_NAMES


def _resolved(row):
    return (
        row.get("realized_r") is not None
        and row.get("outcome") not in ("UNRESOLVED", "INVALID_RISK")
    )


def _matrix(rows):
    x = np.asarray([
        [float((row.get("v4_features") or {}).get(name, 0.0)) for name in FEATURE_NAMES]
        for row in rows
    ], dtype=float)
    y = np.asarray([
        1.0 if float(row.get("realized_r") or 0.0) > 0.0 else 0.0
        for row in rows
    ], dtype=float)
    return x, y


def _sigmoid(z):
    z = np.clip(z, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(rows):
    rows = [row for row in rows if _resolved(row)]
    if len(rows) < max(2, V4_MIN_TRAIN_SAMPLES):
        return None

    x, y = _matrix(rows)
    if y.min() == y.max():
        return None

    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    xs = (x - mean) / std

    # Bias is separated so L2 does not regularize the intercept.
    w = np.zeros(xs.shape[1], dtype=float)
    base_rate = min(0.999, max(0.001, float(y.mean())))
    b = math.log(base_rate / (1.0 - base_rate))

    n = float(len(rows))
    for _ in range(max(10, int(V4_LOGISTIC_STEPS))):
        p = _sigmoid(xs @ w + b)
        err = p - y
        grad_w = (xs.T @ err) / n + float(V4_LOGISTIC_L2) * w
        grad_b = float(err.mean())
        w -= float(V4_LOGISTIC_LR) * grad_w
        b -= float(V4_LOGISTIC_LR) * grad_b

    realized = np.asarray([float(row.get("realized_r") or 0.0) for row in rows])
    pos = realized[realized > 0]
    neg = realized[realized <= 0]
    if len(pos) == 0 or len(neg) == 0:
        return None

    return {
        "mean": mean,
        "std": std,
        "weights": w,
        "bias": b,
        "avg_win_r": float(pos.mean()),
        "avg_loss_r": float(neg.mean()),
        "train_samples": len(rows),
        "train_positive_rate": float(y.mean()),
    }


def predict_probability(model, row):
    x = np.asarray([
        float((row.get("v4_features") or {}).get(name, 0.0))
        for name in FEATURE_NAMES
    ], dtype=float)
    xs = (x - model["mean"]) / model["std"]
    return float(_sigmoid(np.asarray([xs @ model["weights"] + model["bias"]]))[0])


def _edge_state(train_rows, engine, regime_key):
    engine_rows = [r for r in train_rows if r.get("v3_engine") == engine]
    em = metrics(engine_rows)
    engine_active = bool(
        int(em.get("resolved") or 0) >= V4_MIN_ENGINE_SAMPLES
        and float(em.get("expectancy_r") or -999.0) > V4_ENGINE_MIN_EXPECTANCY
        and float(em.get("profit_factor") or 0.0) >= V4_ENGINE_MIN_PF
    )

    regime_rows = [
        r for r in engine_rows
        if r.get("v4_regime_key") == regime_key
    ]
    rm = metrics(regime_rows)
    regime_active = bool(
        int(rm.get("resolved") or 0) >= V4_MIN_REGIME_SAMPLES
        and float(rm.get("expectancy_r") or -999.0) > 0.0
        and float(rm.get("profit_factor") or 0.0) >= 1.0
    )

    return {
        "engine_state": "ACTIVE" if engine_active else "SHADOW",
        "regime_state": (
            "ACTIVE"
            if regime_active
            else ("INSUFFICIENT" if int(rm.get("resolved") or 0) < V4_MIN_REGIME_SAMPLES else "SHADOW")
        ),
        "engine_train_metrics": em,
        "regime_train_metrics": rm,
    }


def _score_rows(train_rows, test_rows, phase, fold_name, train_start, train_end):
    model = fit_logistic(train_rows)
    if model is None:
        for row in test_rows:
            row["v4_phase"] = phase
            row["v4_fold"] = fold_name
            row["v4_status"] = "SHADOW"
            row["v4_reject_reason"] = "insufficient_meta_training"
        return {
            "fold": fold_name,
            "phase": phase,
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "train_samples": len(train_rows),
            "test_samples": len(test_rows),
            "model_fitted": False,
        }

    for row in test_rows:
        p = predict_probability(model, row)
        expected_r = (
            p * float(model["avg_win_r"])
            + (1.0 - p) * float(model["avg_loss_r"])
        )
        edge = _edge_state(
            train_rows,
            row.get("v3_engine"),
            row.get("v4_regime_key"),
        )

        pass_meta = bool(
            p >= V4_MIN_PROBABILITY
            and expected_r >= V4_MIN_EXPECTED_R
        )
        pass_edge = bool(
            edge["engine_state"] == "ACTIVE"
            and edge["regime_state"] == "ACTIVE"
        )
        status = "ENTRY_READY" if pass_meta and pass_edge else "SHADOW"

        reasons = []
        if p < V4_MIN_PROBABILITY:
            reasons.append("probability_below_threshold")
        if expected_r < V4_MIN_EXPECTED_R:
            reasons.append("expected_r_below_threshold")
        if edge["engine_state"] != "ACTIVE":
            reasons.append("engine_auto_demoted")
        if edge["regime_state"] != "ACTIVE":
            reasons.append("regime_not_proven")

        row.update({
            "v4_phase": phase,
            "v4_fold": fold_name,
            "v4_probability": round(p, 6),
            "v4_expected_r": round(expected_r, 6),
            "v4_status": status,
            "v4_engine_state": edge["engine_state"],
            "v4_regime_state": edge["regime_state"],
            "v4_reject_reason": ",".join(reasons) if reasons else None,
            "v4_train_samples": int(model["train_samples"]),
            "v4_train_positive_rate": round(float(model["train_positive_rate"]), 6),
            "v4_train_avg_win_r": round(float(model["avg_win_r"]), 6),
            "v4_train_avg_loss_r": round(float(model["avg_loss_r"]), 6),
            "v4_engine_train_expectancy": edge["engine_train_metrics"].get("expectancy_r"),
            "v4_engine_train_pf": edge["engine_train_metrics"].get("profit_factor"),
            "v4_regime_train_expectancy": edge["regime_train_metrics"].get("expectancy_r"),
            "v4_regime_train_pf": edge["regime_train_metrics"].get("profit_factor"),
        })

    return {
        "fold": fold_name,
        "phase": phase,
        "train_start": train_start.isoformat(),
        "train_end": train_end.isoformat(),
        "train_samples": len(train_rows),
        "test_samples": len(test_rows),
        "model_fitted": True,
        "avg_win_r": round(float(model["avg_win_r"]), 6),
        "avg_loss_r": round(float(model["avg_loss_r"]), 6),
    }


def apply_walkforward_meta(trades):
    rows = [t for t in trades if _resolved(t)]
    rows.sort(key=lambda r: pd.Timestamp(r["signal_time"]))
    for row in rows:
        row.setdefault("v4_status", "UNSCORED")
        row.setdefault("v4_phase", "UNSCORED")

    if not rows:
        return {"folds": [], "holdout": None, "note": "No resolved candidates."}

    first = pd.Timestamp(rows[0]["signal_time"])
    last = pd.Timestamp(rows[-1]["signal_time"])
    embargo = pd.Timedelta(hours=V4_EMBARGO_HOURS)
    train_span = pd.Timedelta(days=V4_TRAIN_DAYS)
    test_span = pd.Timedelta(days=V4_TEST_DAYS)
    holdout_span = pd.Timedelta(days=V4_FINAL_HOLDOUT_DAYS)

    holdout_start = max(first, last - holdout_span)
    test_start = first + train_span + embargo
    folds = []
    fold_no = 1

    while test_start < holdout_start:
        test_end = min(test_start + test_span, holdout_start)
        train_end = test_start - embargo
        train_start = train_end - train_span

        train_rows = [
            r for r in rows
            if train_start <= pd.Timestamp(r["signal_time"]) < train_end
        ]
        test_rows = [
            r for r in rows
            if test_start <= pd.Timestamp(r["signal_time"]) < test_end
        ]
        folds.append(_score_rows(
            train_rows,
            test_rows,
            phase="WALK_FORWARD",
            fold_name=f"WF{fold_no:02d}",
            train_start=train_start,
            train_end=train_end,
        ))
        fold_no += 1
        test_start = test_end

    holdout_train_end = holdout_start - embargo
    holdout_train_start = holdout_train_end - train_span
    holdout_train = [
        r for r in rows
        if holdout_train_start <= pd.Timestamp(r["signal_time"]) < holdout_train_end
    ]
    holdout_rows = [
        r for r in rows
        if holdout_start <= pd.Timestamp(r["signal_time"]) <= last
    ]
    holdout = _score_rows(
        holdout_train,
        holdout_rows,
        phase="FINAL_HOLDOUT",
        fold_name="FINAL_HOLDOUT",
        train_start=holdout_train_start,
        train_end=holdout_train_end,
    )
    holdout["holdout_start"] = holdout_start.isoformat()
    holdout["holdout_end"] = last.isoformat()

    unscored = sum(1 for r in rows if r.get("v4_status") == "UNSCORED")
    return {
        "first_signal": first.isoformat(),
        "last_signal": last.isoformat(),
        "train_days": V4_TRAIN_DAYS,
        "test_days": V4_TEST_DAYS,
        "embargo_hours": V4_EMBARGO_HOURS,
        "final_holdout_days": V4_FINAL_HOLDOUT_DAYS,
        "folds": folds,
        "holdout": holdout,
        "unscored_warmup_candidates": unscored,
        "note": (
            "The final holdout is scored by one model trained only on the prior "
            "training window ending before the embargo. No holdout outcome is "
            "used to fit or route its own signal."
        ),
    }
