from collections import defaultdict


def _metrics(rows):
    resolved = [r for r in rows if r.get("outcome") in ("WIN", "LOSS")]
    wins = [r for r in resolved if r.get("outcome") == "WIN"]
    losses = [r for r in resolved if r.get("outcome") == "LOSS"]

    gross_win_r = sum(float(r.get("realized_r") or 0) for r in wins)
    gross_loss_r = abs(sum(float(r.get("realized_r") or 0) for r in losses))
    expectancy = (
        sum(float(r.get("realized_r") or 0) for r in resolved) / len(resolved)
        if resolved else None
    )
    profit_factor = (
        gross_win_r / gross_loss_r
        if gross_loss_r > 0 else (999.0 if gross_win_r > 0 else None)
    )

    return {
        "signals": len(rows),
        "resolved": len(resolved),
        "wins": len(wins),
        "losses": len(losses),
        "unresolved": len(rows) - len(resolved),
        "win_rate_pct": round(len(wins) / len(resolved) * 100.0, 2) if resolved else None,
        "expectancy_r": round(expectancy, 4) if expectancy is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "avg_mae_r": round(
            sum(float(r.get("mae_r") or 0) for r in rows) / len(rows), 4
        ) if rows else None,
        "avg_mfe_r": round(
            sum(float(r.get("mfe_r") or 0) for r in rows) / len(rows), 4
        ) if rows else None,
    }


def _score_bin(score):
    score = float(score or 0)
    if score >= 90:
        return "90+"
    if score >= 80:
        return "80-89"
    if score >= 70:
        return "70-79"
    return "60-69"


def _recommendation(metrics):
    samples = int(metrics.get("resolved") or 0)
    expectancy = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor")

    if samples < 20:
        return {
            "action": "WAIT_FOR_SAMPLE",
            "reason": "Need at least 20 resolved signals before changing live weights.",
        }
    if expectancy is not None and pf is not None and expectancy >= 0.20 and pf >= 1.30:
        return {
            "action": "PROMOTE",
            "reason": "Positive expectancy and profit factor with sufficient sample.",
        }
    if expectancy is not None and pf is not None and (expectancy < 0 or pf < 0.90):
        return {
            "action": "DEMOTE",
            "reason": "Negative/weak edge in resolved historical signals.",
        }
    return {
        "action": "KEEP",
        "reason": "Edge is not strong enough to promote or weak enough to demote.",
    }


def build_calibration(trades):
    by_model = defaultdict(list)
    by_score = defaultdict(list)
    by_status = defaultdict(list)

    for trade in trades:
        by_model[trade.get("model", "UNCLASSIFIED")].append(trade)
        by_score[_score_bin(trade.get("score"))].append(trade)
        by_status[trade.get("status", "UNKNOWN")].append(trade)

    model_stats = {}
    for key, rows in sorted(by_model.items()):
        stats = _metrics(rows)
        stats["recommendation"] = _recommendation(stats)
        model_stats[key] = stats

    return {
        "overall": _metrics(trades),
        "by_model": model_stats,
        "by_score_bin": {
            key: _metrics(rows)
            for key, rows in sorted(by_score.items())
        },
        "by_status": {
            key: _metrics(rows)
            for key, rows in sorted(by_status.items())
        },
    }


def equity_curve_metrics(trades):
    resolved = sorted(
        [r for r in trades if r.get("outcome") in ("WIN", "LOSS")],
        key=lambda r: str(r.get("signal_time")),
    )
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    longest_loss_streak = 0
    current_loss_streak = 0

    for trade in resolved:
        equity += float(trade.get("realized_r") or 0)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if trade.get("outcome") == "LOSS":
            current_loss_streak += 1
            longest_loss_streak = max(longest_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0

    return {
        "net_r": round(equity, 4),
        "max_drawdown_r": round(max_drawdown, 4),
        "longest_loss_streak": longest_loss_streak,
    }
