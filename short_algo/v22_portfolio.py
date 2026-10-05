"""V2.2 market ranking, portfolio simulation and time-window robustness."""

from collections import defaultdict
from datetime import timedelta

import pandas as pd


def _is_resolved(t):
    return t.get("realized_r") is not None and t.get("outcome") not in ("UNRESOLVED", "INVALID_RISK")


def rank_v22_entries(trades, max_per_timestamp=3, max_concurrent=3):
    """Mark the highest scoring executable V2.2 setups across the whole market."""
    candidates = [
        t for t in trades
        if t.get("strategy_family") == "V22_CORE"
        and t.get("v22_status") == "ENTRY_READY"
        and _is_resolved(t)
    ]

    by_time = defaultdict(list)
    for trade in candidates:
        by_time[str(trade.get("signal_time"))].append(trade)

    shortlisted = []
    for _, rows in sorted(by_time.items()):
        rows.sort(
            key=lambda x: (
                -float(x.get("v22_score") or 0.0),
                -float(x.get("return_24h_pct") or 0.0),
                str(x.get("symbol") or ""),
            )
        )
        shortlisted.extend(rows[:max(1, int(max_per_timestamp))])

    shortlisted.sort(key=lambda x: (pd.Timestamp(x["signal_time"]), -float(x.get("v22_score") or 0.0)))

    selected = []
    open_until = []
    for trade in shortlisted:
        entry_time = pd.Timestamp(trade["signal_time"])
        open_until = [ts for ts in open_until if ts > entry_time]
        if len(open_until) >= max(1, int(max_concurrent)):
            continue

        exit_time = trade.get("exit_time")
        if exit_time:
            exit_ts = pd.Timestamp(exit_time)
        else:
            bars = int(trade.get("bars_to_outcome") or 1)
            exit_ts = entry_time + pd.Timedelta(minutes=15 * bars)

        trade["v22_ranked"] = True
        trade["v22_market_rank"] = 1 + sum(
            1 for x in shortlisted
            if x.get("signal_time") == trade.get("signal_time")
            and float(x.get("v22_score") or 0) > float(trade.get("v22_score") or 0)
        )
        selected.append(trade)
        open_until.append(exit_ts)

    selected_ids = {id(t) for t in selected}
    for trade in trades:
        if trade.get("strategy_family") == "V22_CORE" and "v22_ranked" not in trade:
            trade["v22_ranked"] = id(trade) in selected_ids

    return selected


def portfolio_metrics(trades, starting_equity=10000.0, risk_pct=0.5):
    rows = [t for t in trades if _is_resolved(t)]
    rows.sort(key=lambda x: pd.Timestamp(x.get("exit_time") or x["signal_time"]))

    equity = float(starting_equity)
    peak = equity
    max_dd_pct = 0.0
    wins = 0
    losses = 0

    for trade in rows:
        r = float(trade.get("realized_r") or 0.0)
        equity *= max(0.0, 1.0 + r * float(risk_pct) / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - equity) / peak * 100.0)
        if r > 0:
            wins += 1
        else:
            losses += 1

    return {
        "starting_equity": round(float(starting_equity), 2),
        "ending_equity": round(equity, 2),
        "return_pct": round((equity / float(starting_equity) - 1.0) * 100.0, 3),
        "risk_pct_per_trade": float(risk_pct),
        "trades": len(rows),
        "wins": wins,
        "losses": losses,
        "max_drawdown_pct": round(max_dd_pct, 3),
    }


def _passes_v22_hard_gate(trade):
    gate = trade.get("v22_gate") or {}
    return bool(
        gate.get("context_ok")
        and gate.get("confirmation_15m_ok")
        and gate.get("location_ok")
        and gate.get("risk_ok")
        and not gate.get("btc_risk_on_block")
    )


def walk_forward_threshold(trades, train_days=60, test_days=30, thresholds=(60, 65, 70, 75, 80)):
    # Threshold tuning is allowed to vary only the V2.2 score. All structural
    # hard gates remain fixed in both train and test windows so walk-forward
    # cannot "cheat" by relaxing 15m confirmation, location, risk, or BTC regime.
    candidates = [
        t for t in trades
        if t.get("strategy_family") == "V22_CORE"
        and t.get("v22_score") is not None
        and _passes_v22_hard_gate(t)
        and _is_resolved(t)
    ]
    if not candidates:
        return {"windows": [], "aggregate_test_expectancy_r": None}

    candidates.sort(key=lambda x: pd.Timestamp(x["signal_time"]))
    first = pd.Timestamp(candidates[0]["signal_time"])
    last = pd.Timestamp(candidates[-1]["signal_time"])
    cursor = first + pd.Timedelta(days=train_days)
    windows = []

    while cursor + pd.Timedelta(days=test_days) <= last + pd.Timedelta(hours=1):
        train_start = cursor - pd.Timedelta(days=train_days)
        train_end = cursor
        test_end = cursor + pd.Timedelta(days=test_days)

        train = [
            t for t in candidates
            if train_start <= pd.Timestamp(t["signal_time"]) < train_end
        ]
        test = [
            t for t in candidates
            if train_end <= pd.Timestamp(t["signal_time"]) < test_end
        ]

        best = None
        for threshold in thresholds:
            sample = [t for t in train if float(t.get("v22_score") or 0) >= threshold]
            if len(sample) < 10:
                continue
            expectancy = sum(float(t.get("realized_r") or 0) for t in sample) / len(sample)
            candidate = (expectancy, len(sample), threshold)
            if best is None or candidate > best:
                best = candidate

        if best is not None:
            threshold = best[2]
            test_selected = [t for t in test if float(t.get("v22_score") or 0) >= threshold]
            test_exp = (
                sum(float(t.get("realized_r") or 0) for t in test_selected) / len(test_selected)
                if test_selected else None
            )
            windows.append({
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_end": test_end.isoformat(),
                "selected_threshold": threshold,
                "train_signals": best[1],
                "train_expectancy_r": round(best[0], 4),
                "test_signals": len(test_selected),
                "test_expectancy_r": None if test_exp is None else round(test_exp, 4),
            })

        cursor += pd.Timedelta(days=test_days)

    tested = [
        w for w in windows
        if w.get("test_expectancy_r") is not None and w.get("test_signals", 0) > 0
    ]
    weighted_n = sum(w["test_signals"] for w in tested)
    aggregate = (
        sum(w["test_expectancy_r"] * w["test_signals"] for w in tested) / weighted_n
        if weighted_n else None
    )
    return {
        "train_days": train_days,
        "test_days": test_days,
        "windows": windows,
        "aggregate_test_signals": weighted_n,
        "aggregate_test_expectancy_r": None if aggregate is None else round(aggregate, 4),
    }
