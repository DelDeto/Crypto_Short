"""Whole-market ranking, cluster control and time robustness for V3."""

from collections import defaultdict

import pandas as pd

from .v3_calibration import metrics


_CLUSTER_MAP = {
    "MEME": {"DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI", "BOME", "MEME", "NEIRO", "BRETT", "POPCAT", "MOG"},
    "AI": {"FET", "TAO", "RENDER", "RNDR", "WLD", "ARKM", "AI", "AGIX", "OCEAN", "VIRTUAL"},
    "L1": {"BTC", "ETH", "SOL", "AVAX", "SUI", "APT", "SEI", "NEAR", "ATOM", "DOT", "ADA", "TON"},
    "DEFI": {"UNI", "AAVE", "CRV", "MKR", "LDO", "ENA", "PENDLE", "COMP", "SNX", "SUSHI"},
}


def symbol_cluster(symbol):
    base = str(symbol or "").upper().split("_", 1)[0]
    for cluster, members in _CLUSTER_MAP.items():
        if base in members:
            return cluster
    return f"OTHER:{base}"


def _resolved(t):
    return t.get("realized_r") is not None and t.get("outcome") not in ("UNRESOLVED", "INVALID_RISK")


def rank_v3_entries(trades, max_per_timestamp=3, max_concurrent=3, max_per_cluster=1):
    candidates = [
        t for t in trades
        if t.get("strategy_family") == "V3_CORE"
        and t.get("v3_primary") is True
        and t.get("v3_status") == "ENTRY_READY"
        and _resolved(t)
    ]

    # Only one executable setup per symbol/timestamp. The primary flag already
    # enforces this, but dedupe again after shard merge for safety.
    deduped = {}
    for trade in candidates:
        key = (trade.get("symbol"), trade.get("signal_time"))
        quality = float(trade.get("v3_score") or 0.0) - 100.0 * float(trade.get("v3_projected_cost_r") or 0.0)
        old = deduped.get(key)
        if old is None or quality > old[0]:
            deduped[key] = (quality, trade)

    by_time = defaultdict(list)
    for quality, trade in deduped.values():
        trade["v3_cluster"] = symbol_cluster(trade.get("symbol"))
        trade["v3_quality"] = round(quality, 3)
        by_time[str(trade.get("signal_time"))].append(trade)

    shortlisted = []
    for _, rows in sorted(by_time.items()):
        rows.sort(key=lambda x: (-float(x.get("v3_quality") or 0.0), str(x.get("symbol") or "")))
        cluster_counts = defaultdict(int)
        rank = 0
        for trade in rows:
            cluster = trade["v3_cluster"]
            if cluster_counts[cluster] >= max(1, int(max_per_cluster)):
                continue
            rank += 1
            trade["v3_market_rank"] = rank
            shortlisted.append(trade)
            cluster_counts[cluster] += 1
            if rank >= max(1, int(max_per_timestamp)):
                break

    shortlisted.sort(key=lambda x: pd.Timestamp(x["signal_time"]))
    selected = []
    open_positions = []

    for trade in shortlisted:
        entry_time = pd.Timestamp(trade["signal_time"])
        open_positions = [p for p in open_positions if p["exit"] > entry_time]

        if len(open_positions) >= max(1, int(max_concurrent)):
            continue

        cluster = trade.get("v3_cluster")
        if sum(1 for p in open_positions if p["cluster"] == cluster) >= max(1, int(max_per_cluster)):
            continue

        exit_time = trade.get("exit_time")
        if exit_time:
            exit_ts = pd.Timestamp(exit_time)
        else:
            bars = max(1, int(trade.get("bars_to_outcome") or 1))
            exit_ts = entry_time + pd.Timedelta(minutes=15 * bars)

        trade["v3_ranked"] = True
        selected.append(trade)
        open_positions.append({"exit": exit_ts, "cluster": cluster})

    selected_ids = {id(t) for t in selected}
    for trade in trades:
        if trade.get("strategy_family") == "V3_CORE":
            trade["v3_ranked"] = id(trade) in selected_ids

    return selected


def portfolio_metrics(trades, starting_equity=10000.0, risk_pct=0.5):
    rows = [t for t in trades if _resolved(t)]
    rows.sort(key=lambda x: pd.Timestamp(x.get("exit_time") or x["signal_time"]))

    equity = float(starting_equity)
    peak = equity
    max_dd = 0.0
    for trade in rows:
        r = float(trade.get("realized_r") or 0.0)
        equity *= max(0.0, 1.0 + r * float(risk_pct) / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    return {
        "starting_equity": round(float(starting_equity), 2),
        "ending_equity": round(equity, 2),
        "return_pct": round((equity / float(starting_equity) - 1.0) * 100.0, 3),
        "risk_pct_per_trade": float(risk_pct),
        "trades": len(rows),
        "max_drawdown_pct": round(max_dd, 3),
    }


def temporal_robustness(trades):
    rows = [
        t for t in trades
        if t.get("v3_primary") is True
        and t.get("v3_status") == "ENTRY_READY"
        and _resolved(t)
    ]
    if not rows:
        return {"older_half": metrics([]), "recent_half": metrics([]), "quarters": []}

    rows.sort(key=lambda x: pd.Timestamp(x["signal_time"]))
    first = pd.Timestamp(rows[0]["signal_time"])
    last = pd.Timestamp(rows[-1]["signal_time"])
    midpoint = first + (last - first) / 2

    older = [t for t in rows if pd.Timestamp(t["signal_time"]) < midpoint]
    recent = [t for t in rows if pd.Timestamp(t["signal_time"]) >= midpoint]

    quarters = []
    span = last - first
    for i in range(4):
        start = first + span * (i / 4.0)
        end = first + span * ((i + 1) / 4.0) if i < 3 else last + pd.Timedelta(seconds=1)
        sample = [t for t in rows if start <= pd.Timestamp(t["signal_time"]) < end]
        quarters.append({
            "quarter": i + 1,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "metrics": metrics(sample),
        })

    return {
        "first_signal": first.isoformat(),
        "last_signal": last.isoformat(),
        "midpoint": midpoint.isoformat(),
        "older_half": metrics(older),
        "recent_half": metrics(recent),
        "quarters": quarters,
        "note": "Older half is a retrospective holdout relative to V3 rules inspired by the recent V2.2.1 sample; it is not a future live OOS test.",
    }
