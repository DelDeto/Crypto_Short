import json
import os
import sys
from glob import glob

from .calibration_v2 import build_calibration, equity_curve_metrics
from .config import (
    OUTPUT_DIR,
    V22_MAX_PER_TIMESTAMP,
    V22_MAX_CONCURRENT,
    V22_PORTFOLIO_RISK_PCT,
    V22_STARTING_EQUITY,
    V22_WALK_FORWARD_TRAIN_DAYS,
    V22_WALK_FORWARD_TEST_DAYS,
)
from .v22_portfolio import rank_v22_entries, portfolio_metrics, walk_forward_threshold
from .v2_main import _summary_markdown, _write_json, _write_trades_csv


def _load_shards(root):
    paths = sorted(glob(os.path.join(root, "**", "v2_backtest.json"), recursive=True))
    shards = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["_source_path"] = path
        shards.append(payload)
    return shards


def _dedupe_trades(trades):
    seen = set()
    unique = []
    for trade in trades:
        key = (
            trade.get("strategy_family"),
            trade.get("symbol"),
            trade.get("signal_time"),
            trade.get("model"),
            trade.get("entry"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(trade)
    unique.sort(key=lambda x: (str(x.get("signal_time")), x.get("symbol", "")))
    return unique


def merge_reports(shards):
    if not shards:
        raise RuntimeError("No shard reports found.")

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
            "signals": len(report.get("trades") or []),
            "errors": len(report.get("errors") or []),
            "source_path": report.get("_source_path"),
        })

    trades = _dedupe_trades(trades)
    symbols = sorted(set(symbols))

    ranked_v22 = rank_v22_entries(
        trades,
        max_per_timestamp=V22_MAX_PER_TIMESTAMP,
        max_concurrent=V22_MAX_CONCURRENT,
    )
    calibration = build_calibration(trades)

    core_trades = [
        trade for trade in trades
        if trade.get("strategy_family") == "V21_CORE"
    ]
    v21_entry_trades = [
        trade for trade in core_trades
        if trade.get("v21_status") == "ENTRY_READY"
    ]
    v22_entry_trades = [
        trade for trade in trades
        if trade.get("strategy_family") == "V22_CORE"
        and trade.get("v22_status") == "ENTRY_READY"
    ]
    baseline_trades = [
        trade for trade in trades
        if trade.get("strategy_family") == "BOLLINGER_BASELINE"
    ]

    equity = equity_curve_metrics(core_trades)
    v21_equity = equity_curve_metrics(v21_entry_trades)
    v22_equity = equity_curve_metrics(v22_entry_trades)
    v22_ranked_equity = equity_curve_metrics(ranked_v22)
    baseline_equity = equity_curve_metrics(baseline_trades)
    v22_portfolio = portfolio_metrics(
        ranked_v22,
        starting_equity=V22_STARTING_EQUITY,
        risk_pct=V22_PORTFOLIO_RISK_PCT,
    )
    v22_walk_forward = walk_forward_threshold(
        [
            trade for trade in trades
            if trade.get("strategy_family") == "V22_CORE"
        ],
        train_days=V22_WALK_FORWARD_TRAIN_DAYS,
        test_days=V22_WALK_FORWARD_TEST_DAYS,
    )

    first = shards[0]
    periods = {
        (r.get("period_start"), r.get("period_end"))
        for r in shards
    }

    return {
        "engine": "Crypto Short Scanner V2.2 Parallel Backtest",
        "generated_at": first.get("generated_at"),
        "period_start": min(str(r.get("period_start")) for r in shards),
        "period_end": max(str(r.get("period_end")) for r in shards),
        "days": first.get("days"),
        "selected_symbols": symbols,
        "selected_symbol_count": len(symbols),
        "selection_meta": {
            "selection": (first.get("selection_meta") or {}).get("selection"),
            "universe_count": (first.get("selection_meta") or {}).get("universe_count"),
            "symbol_limit": (first.get("selection_meta") or {}).get("symbol_limit"),
            "bias_note": (first.get("selection_meta") or {}).get("bias_note"),
            "parallel_shards_expected": max(
                int(r.get("shard_count") or 1) for r in shards
            ),
            "parallel_shards_found": len(shards),
            "periods_identical": len(periods) == 1,
        },
        "settings": first.get("settings") or {},
        "calibration": calibration,
        "equity_sequence": equity,
        "v21_equity_sequence": v21_equity,
        "v22_equity_sequence": v22_equity,
        "v22_ranked_equity_sequence": v22_ranked_equity,
        "v22_portfolio": v22_portfolio,
        "v22_walk_forward": v22_walk_forward,
        "baseline_equity_sequence": baseline_equity,
        "trades": trades,
        "errors": errors,
        "shards": source_shards,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    shards = _load_shards(root)
    if not shards:
        print(f"No shard reports found under {root}", file=sys.stderr)
        return 2

    expected = max(int(r.get("shard_count") or 1) for r in shards)
    found_indices = {
        int(r.get("shard_index"))
        for r in shards
        if r.get("shard_index") is not None
    }
    expected_indices = set(range(expected))

    if found_indices != expected_indices:
        print(
            "Incomplete shard set: "
            f"expected={sorted(expected_indices)} found={sorted(found_indices)}",
            file=sys.stderr,
        )
        return 3

    report = merge_reports(shards)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(os.path.join(OUTPUT_DIR, "v2_backtest.json"), report)
    _write_trades_csv(
        os.path.join(OUTPUT_DIR, "v2_trades.csv"),
        report.get("trades") or [],
    )
    _write_json(
        os.path.join(OUTPUT_DIR, "v2_calibration.json"),
        report.get("calibration") or {},
    )
    with open(
        os.path.join(OUTPUT_DIR, "v2_summary.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(_summary_markdown(report))

    overall = (report.get("calibration") or {}).get("overall") or {}
    entry_ready = (report.get("calibration") or {}).get("entry_ready") or {}
    print(json.dumps({
        "shards": len(shards),
        "symbols": report.get("selected_symbol_count"),
        "signals": overall.get("signals"),
        "resolved": overall.get("resolved"),
        "entry_ready_signals": entry_ready.get("signals"),
        "entry_ready_resolved": entry_ready.get("resolved"),
        "v21_entry_ready_signals": ((report.get("calibration") or {}).get("v21_entry_ready") or {}).get("signals"),
        "v21_entry_ready_resolved": ((report.get("calibration") or {}).get("v21_entry_ready") or {}).get("resolved"),
        "v22_entry_ready_signals": ((report.get("calibration") or {}).get("v22_entry_ready") or {}).get("signals"),
        "v22_entry_ready_resolved": ((report.get("calibration") or {}).get("v22_entry_ready") or {}).get("resolved"),
        "v22_ranked_signals": ((report.get("calibration") or {}).get("v22_ranked_portfolio") or {}).get("signals"),
        "win_rate_pct": overall.get("win_rate_pct"),
        "expectancy_r": overall.get("expectancy_r"),
        "profit_factor": overall.get("profit_factor"),
        "equity_sequence": report.get("equity_sequence"),
        "v21_equity_sequence": report.get("v21_equity_sequence"),
        "v22_equity_sequence": report.get("v22_equity_sequence"),
        "v22_ranked_equity_sequence": report.get("v22_ranked_equity_sequence"),
        "v22_portfolio": report.get("v22_portfolio"),
        "v22_walk_forward": report.get("v22_walk_forward"),
        "baseline_equity_sequence": report.get("baseline_equity_sequence"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
