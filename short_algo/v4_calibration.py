"""Calibration and diagnostics for V4 out-of-sample meta labels."""

from collections import Counter, defaultdict

from .v3_calibration import equity_curve_metrics, metrics


def _probability_bin(value):
    if value is None:
        return "UNSCORED"
    p = float(value)
    if p < 0.30:
        return "<0.30"
    if p < 0.35:
        return "0.30-0.35"
    if p < 0.40:
        return "0.35-0.40"
    if p < 0.45:
        return "0.40-0.45"
    if p < 0.50:
        return "0.45-0.50"
    return "0.50+"


def _meta_metrics(rows):
    base = metrics(rows)
    scored = [
        row for row in rows
        if row.get("v4_probability") is not None
        and row.get("realized_r") is not None
    ]
    if not scored:
        return {
            **base,
            "avg_predicted_probability": None,
            "avg_predicted_expected_r": None,
            "brier_score": None,
        }

    probs = [float(row["v4_probability"]) for row in scored]
    labels = [
        1.0 if float(row.get("realized_r") or 0.0) > 0.0 else 0.0
        for row in scored
    ]
    expected = [
        float(row.get("v4_expected_r") or 0.0)
        for row in scored
    ]
    brier = sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(scored)

    return {
        **base,
        "avg_predicted_probability": round(sum(probs) / len(probs), 4),
        "avg_predicted_expected_r": round(sum(expected) / len(expected), 4),
        "brier_score": round(brier, 5),
    }


def build_v4_calibration(trades, ranked):
    scored = [
        row for row in trades
        if row.get("v4_phase") in ("WALK_FORWARD", "FINAL_HOLDOUT")
        and row.get("v4_probability") is not None
    ]
    entry = [row for row in scored if row.get("v4_status") == "ENTRY_READY"]
    shadow = [row for row in scored if row.get("v4_status") == "SHADOW"]
    holdout = [row for row in scored if row.get("v4_phase") == "FINAL_HOLDOUT"]
    holdout_entry = [
        row for row in holdout if row.get("v4_status") == "ENTRY_READY"
    ]

    by_engine = defaultdict(list)
    by_regime = defaultdict(list)
    by_phase = defaultdict(list)
    by_probability = defaultdict(list)

    for row in entry:
        by_engine[row.get("v3_engine", "UNKNOWN")].append(row)
        by_regime[row.get("v4_regime_key", "UNKNOWN")].append(row)
        by_phase[row.get("v4_phase", "UNKNOWN")].append(row)
        by_probability[_probability_bin(row.get("v4_probability"))].append(row)

    states = Counter(
        f"{row.get('v4_engine_state')}|{row.get('v4_regime_state')}"
        for row in scored
    )

    return {
        "all_raw_candidates": metrics(trades),
        "all_scored_candidates": _meta_metrics(scored),
        "entry_ready": _meta_metrics(entry),
        "shadow": _meta_metrics(shadow),
        "final_holdout": _meta_metrics(holdout),
        "final_holdout_entry_ready": _meta_metrics(holdout_entry),
        "ranked_portfolio": _meta_metrics(ranked),
        "by_engine": {
            key: _meta_metrics(rows)
            for key, rows in sorted(by_engine.items())
        },
        "by_regime": {
            key: _meta_metrics(rows)
            for key, rows in sorted(by_regime.items())
        },
        "by_phase": {
            key: _meta_metrics(rows)
            for key, rows in sorted(by_phase.items())
        },
        "by_probability_bin": {
            key: _meta_metrics(rows)
            for key, rows in sorted(by_probability.items())
        },
        "edge_state_counts": dict(sorted(states.items())),
        "entry_equity": equity_curve_metrics(entry),
        "holdout_entry_equity": equity_curve_metrics(holdout_entry),
        "ranked_equity": equity_curve_metrics(ranked),
    }
