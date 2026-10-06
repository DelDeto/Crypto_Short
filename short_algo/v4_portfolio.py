"""V4 portfolio construction ranks only by out-of-sample expected R."""

from collections import defaultdict

import pandas as pd

from .v3_portfolio import portfolio_metrics, symbol_cluster


def _resolved(row):
    return (
        row.get("realized_r") is not None
        and row.get("outcome") not in ("UNRESOLVED", "INVALID_RISK")
    )


def rank_v4_entries(
    trades,
    max_per_timestamp=3,
    max_concurrent=3,
    max_per_cluster=1,
):
    candidates = [
        row for row in trades
        if row.get("v4_status") == "ENTRY_READY"
        and _resolved(row)
    ]

    # One setup per symbol/timestamp. If several rule engines fire, keep the
    # one with the highest OOS expected R, then probability.
    deduped = {}
    for row in candidates:
        key = (row.get("symbol"), row.get("signal_time"))
        quality = (
            float(row.get("v4_expected_r") or -999.0),
            float(row.get("v4_probability") or 0.0),
        )
        old = deduped.get(key)
        if old is None or quality > old[0]:
            deduped[key] = (quality, row)

    by_time = defaultdict(list)
    for quality, row in deduped.values():
        row["v4_cluster"] = symbol_cluster(row.get("symbol"))
        row["v4_quality"] = round(float(quality[0]), 6)
        by_time[str(row.get("signal_time"))].append(row)

    shortlisted = []
    for _, rows in sorted(by_time.items()):
        rows.sort(key=lambda x: (
            -float(x.get("v4_expected_r") or -999.0),
            -float(x.get("v4_probability") or 0.0),
            str(x.get("symbol") or ""),
        ))
        cluster_counts = defaultdict(int)
        for rank, row in enumerate(rows, start=1):
            cluster = row["v4_cluster"]
            if cluster_counts[cluster] >= max(1, int(max_per_cluster)):
                continue
            row["v4_market_rank"] = rank
            shortlisted.append(row)
            cluster_counts[cluster] += 1
            if sum(cluster_counts.values()) >= max(1, int(max_per_timestamp)):
                break

    shortlisted.sort(key=lambda x: pd.Timestamp(x["signal_time"]))
    selected = []
    open_positions = []

    for row in shortlisted:
        entry_time = pd.Timestamp(row["signal_time"])
        open_positions = [p for p in open_positions if p["exit"] > entry_time]

        if len(open_positions) >= max(1, int(max_concurrent)):
            continue

        cluster = row.get("v4_cluster")
        same_cluster = sum(
            1 for p in open_positions if p["cluster"] == cluster
        )
        if same_cluster >= max(1, int(max_per_cluster)):
            continue

        exit_time = row.get("exit_time")
        if exit_time:
            exit_ts = pd.Timestamp(exit_time)
        else:
            bars = max(1, int(row.get("bars_to_outcome") or 1))
            exit_ts = entry_time + pd.Timedelta(minutes=15 * bars)

        row["v4_ranked"] = True
        selected.append(row)
        open_positions.append({"exit": exit_ts, "cluster": cluster})

    selected_ids = {id(row) for row in selected}
    for row in trades:
        row["v4_ranked"] = id(row) in selected_ids

    return selected


__all__ = ["rank_v4_entries", "portfolio_metrics"]
