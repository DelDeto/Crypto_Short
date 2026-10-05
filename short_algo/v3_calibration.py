"""Calibration helpers for V3 research."""

from collections import Counter, defaultdict


def metrics(rows):
    resolved = [
        r for r in rows
        if r.get("realized_r") is not None
        and r.get("outcome") not in ("UNRESOLVED", "INVALID_RISK")
    ]
    positive = [r for r in resolved if float(r.get("realized_r") or 0.0) > 0.0]
    negative = [r for r in resolved if float(r.get("realized_r") or 0.0) <= 0.0]
    barrier = [r for r in resolved if r.get("outcome") in ("WIN", "LOSS")]
    barrier_wins = [r for r in barrier if r.get("outcome") == "WIN"]

    gross_profit = sum(max(0.0, float(r.get("realized_r") or 0.0)) for r in resolved)
    gross_loss = abs(sum(min(0.0, float(r.get("realized_r") or 0.0)) for r in resolved))
    expectancy = (
        sum(float(r.get("realized_r") or 0.0) for r in resolved) / len(resolved)
        if resolved else None
    )
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else None)
    outcome_counts = Counter(str(r.get("outcome") or "UNKNOWN") for r in rows)

    return {
        "signals": len(rows),
        "resolved": len(resolved),
        "net_profitable": len(positive),
        "net_unprofitable": len(negative),
        "net_profitable_rate_pct": round(len(positive) / len(resolved) * 100.0, 2) if resolved else None,
        "barrier_decisions": len(barrier),
        "barrier_wins": len(barrier_wins),
        "tp_before_sl_rate_pct": round(len(barrier_wins) / len(barrier) * 100.0, 2) if barrier else None,
        "time_exit_count": sum(outcome_counts.get(x, 0) for x in ("TIME_EXIT_WIN", "TIME_EXIT_LOSS")),
        "expectancy_r": round(expectancy, 4) if expectancy is not None else None,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "avg_cost_r": round(
            sum(float(r.get("cost_r") or 0.0) for r in resolved) / len(resolved), 4
        ) if resolved else None,
        "avg_mae_r": round(
            sum(float(r.get("mae_r") or 0.0) for r in resolved if r.get("mae_r") is not None)
            / max(1, sum(1 for r in resolved if r.get("mae_r") is not None)),
            4,
        ) if resolved else None,
        "avg_mfe_r": round(
            sum(float(r.get("mfe_r") or 0.0) for r in resolved if r.get("mfe_r") is not None)
            / max(1, sum(1 for r in resolved if r.get("mfe_r") is not None)),
            4,
        ) if resolved else None,
        "outcomes": dict(sorted(outcome_counts.items())),
    }


def _score_bin(score):
    score = float(score or 0.0)
    if score >= 85:
        return "85+"
    if score >= 80:
        return "80-84"
    if score >= 75:
        return "75-79"
    if score >= 70:
        return "70-74"
    if score >= 65:
        return "65-69"
    if score >= 60:
        return "60-64"
    return "<60"


def _cost_bin(cost):
    cost = float(cost or 0.0)
    if cost <= 0.04:
        return "<=0.04R"
    if cost <= 0.06:
        return "0.04-0.06R"
    if cost <= 0.08:
        return "0.06-0.08R"
    return "0.08-0.10R"


def build_v3_calibration(trades):
    core = [t for t in trades if t.get("strategy_family") == "V3_CORE"]
    primary = [t for t in core if t.get("v3_primary") is True]
    entry = [t for t in primary if t.get("v3_status") == "ENTRY_READY"]

    by_engine = defaultdict(list)
    by_regime = defaultdict(list)
    by_score = defaultdict(list)
    by_cost = defaultdict(list)

    for trade in core:
        if trade.get("v3_status") == "ENTRY_READY":
            by_engine[trade.get("v3_engine", "UNKNOWN")].append(trade)
    for trade in entry:
        by_regime[trade.get("v3_regime", "UNKNOWN")].append(trade)
        by_score[_score_bin(trade.get("v3_score"))].append(trade)
        by_cost[_cost_bin(trade.get("v3_projected_cost_r"))].append(trade)

    return {
        "all_candidates": metrics(core),
        "primary_candidates": metrics(primary),
        "entry_ready": metrics(entry),
        "by_engine": {k: metrics(v) for k, v in sorted(by_engine.items())},
        "by_regime": {k: metrics(v) for k, v in sorted(by_regime.items())},
        "by_score_bin": {k: metrics(v) for k, v in sorted(by_score.items())},
        "by_cost_bin": {k: metrics(v) for k, v in sorted(by_cost.items())},
    }


def equity_curve_metrics(trades):
    resolved = sorted(
        [
            r for r in trades
            if r.get("realized_r") is not None
            and r.get("outcome") not in ("UNRESOLVED", "INVALID_RISK")
        ],
        key=lambda r: str(r.get("exit_time") or r.get("signal_time")),
    )
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    longest_loss_streak = 0
    streak = 0

    for trade in resolved:
        r = float(trade.get("realized_r") or 0.0)
        equity += r
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if r <= 0:
            streak += 1
            longest_loss_streak = max(longest_loss_streak, streak)
        else:
            streak = 0

    return {
        "net_r": round(equity, 4),
        "max_drawdown_r": round(max_drawdown, 4),
        "longest_loss_streak": longest_loss_streak,
    }
