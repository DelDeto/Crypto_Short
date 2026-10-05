import json
import os
import sys
from glob import glob

from .config import (
    OUTPUT_DIR,
    V3_MAX_CONCURRENT,
    V3_MAX_PER_CLUSTER,
    V3_MAX_PER_TIMESTAMP,
    V3_PORTFOLIO_RISK_PCT,
    V3_STARTING_EQUITY,
)
from .v3_calibration import build_v3_calibration, equity_curve_metrics, metrics
from .v3_main import _summary_markdown, _write_json, _write_trades_csv
from .v3_portfolio import portfolio_metrics, rank_v3_entries, temporal_robustness


def _load_shards(root):
    paths = sorted(glob(os.path.join(root, "**", "v3_backtest.json"), recursive=True))
    shards = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["_source_path"] = path
        shards.append(payload)
    return shards


def _dedupe(trades):
    seen = set()
    out = []
    for trade in trades:
        key = (
            trade.get("symbol"),
            trade.get("signal_time"),
            trade.get("v3_engine"),
            trade.get("entry"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(trade)
    out.sort(key=lambda x: (str(x.get("signal_time")), str(x.get("symbol")), str(x.get("v3_engine"))))
    return out


def merge_reports(shards):
    if not shards:
        raise RuntimeError("No V3 shard reports found.")

    trades = []
    errors = []
    symbols = []
    source_shards = []

    for report in shards:
        trades.extend(report.get("trades") or [])
        errors.extend(report.get("errors") or [])
        symbols.extend(report.get("selected_symbols") or [])
        source_shards.append({
            "shard_index": report.get("shard_index"),
            "shard_count": report.get("shard_count"),
            "symbol_count": report.get("selected_symbol_count"),
            "trades": len(report.get("trades") or []),
            "errors": len(report.get("errors") or []),
            "source_path": report.get("_source_path"),
        })

    trades = _dedupe(trades)
    symbols = sorted(set(symbols))

    ranked = rank_v3_entries(
        trades,
        max_per_timestamp=V3_MAX_PER_TIMESTAMP,
        max_concurrent=V3_MAX_CONCURRENT,
        max_per_cluster=V3_MAX_PER_CLUSTER,
    )

    calibration = build_v3_calibration(trades)
    calibration["ranked_portfolio"] = metrics(ranked)

    primary_entries = [
        t for t in trades
        if t.get("v3_primary") is True and t.get("v3_status") == "ENTRY_READY"
    ]
    entry_equity = equity_curve_metrics(primary_entries)
    ranked_equity = equity_curve_metrics(ranked)
    portfolio = portfolio_metrics(
        ranked,
        starting_equity=V3_STARTING_EQUITY,
        risk_pct=V3_PORTFOLIO_RISK_PCT,
    )
    robustness = temporal_robustness(ranked)

    first = shards[0]
    periods = {(r.get("period_start"), r.get("period_end")) for r in shards}
    return {
        "engine": "Crypto Short V3 Multi-Strategy Parallel Backtest",
        "generated_at": first.get("generated_at"),
        "period_start": min(str(r.get("period_start")) for r in shards),
        "period_end": max(str(r.get("period_end")) for r in shards),
        "days": first.get("days"),
        "selected_symbols": symbols,
        "selected_symbol_count": len(symbols),
        "selection_meta": {
            "selection": (first.get("selection_meta") or {}).get("selection"),
            "universe_count": (first.get("selection_meta") or {}).get("universe_count"),
            "universe_audit": (first.get("selection_meta") or {}).get("universe_audit"),
            "symbol_limit": (first.get("selection_meta") or {}).get("symbol_limit"),
            "bias_note": (first.get("selection_meta") or {}).get("bias_note"),
            "parallel_shards_expected": max(int(r.get("shard_count") or 1) for r in shards),
            "parallel_shards_found": len(shards),
            "periods_identical": len(periods) == 1,
        },
        "settings": first.get("settings") or {},
        "calibration": calibration,
        "entry_equity_sequence": entry_equity,
        "ranked_equity_sequence": ranked_equity,
        "v3_portfolio": portfolio,
        "v3_temporal_robustness": robustness,
        "trades": trades,
        "errors": errors,
        "shards": source_shards,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    shards = _load_shards(root)
    if not shards:
        print(f"No V3 shard reports found under {root}", file=sys.stderr)
        return 2

    expected = max(int(r.get("shard_count") or 1) for r in shards)
    found = {
        int(r.get("shard_index"))
        for r in shards
        if r.get("shard_index") is not None
    }
    if found != set(range(expected)):
        print(f"Incomplete V3 shard set: expected={list(range(expected))} found={sorted(found)}", file=sys.stderr)
        return 3

    report = merge_reports(shards)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v3_backtest.json"), report)
    _write_trades_csv(os.path.join(OUTPUT_DIR, "v3_trades.csv"), report.get("trades") or [])
    _write_json(os.path.join(OUTPUT_DIR, "v3_calibration.json"), report.get("calibration") or {})
    with open(os.path.join(OUTPUT_DIR, "v3_summary.md"), "w", encoding="utf-8") as handle:
        handle.write(_summary_markdown(report))

    print(json.dumps({
        "shards": len(shards),
        "symbols": report.get("selected_symbol_count"),
        "entry_ready": (report.get("calibration") or {}).get("entry_ready"),
        "ranked_portfolio": (report.get("calibration") or {}).get("ranked_portfolio"),
        "portfolio": report.get("v3_portfolio"),
        "temporal_robustness": report.get("v3_temporal_robustness"),
        "by_engine": (report.get("calibration") or {}).get("by_engine"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
