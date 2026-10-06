import json
import os
import sys
from glob import glob

from .config import OUTPUT_DIR
from .v3_portfolio import portfolio_metrics
from .v4_calibration import build_v4_calibration
from .v4_config import (
    V4_MAX_CONCURRENT,
    V4_MAX_PER_CLUSTER,
    V4_MAX_PER_TIMESTAMP,
    V4_PORTFOLIO_RISK_PCT,
    V4_STARTING_EQUITY,
)
from .v4_main import _summary_markdown, _write_json, _write_trades_csv
from .v4_meta import apply_walkforward_meta
from .v4_portfolio import rank_v4_entries


def _load_shards(root):
    paths = sorted(glob(os.path.join(root, "**", "v4_backtest.json"), recursive=True))
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
            trade.get("manifest_id"),
            trade.get("symbol"),
            trade.get("signal_time"),
            trade.get("v3_engine"),
            trade.get("entry"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(trade)
    out.sort(key=lambda x: (
        str(x.get("signal_time")),
        str(x.get("symbol")),
        str(x.get("v3_engine")),
    ))
    return out


def _promotion_gate(calibration, integrity):
    holdout = calibration.get("final_holdout_entry_ready") or {}
    ranked = calibration.get("ranked_portfolio") or {}
    checks = {
        "manifest_integrity": bool(integrity.get("ok")),
        "holdout_sample_50_plus": int(holdout.get("resolved") or 0) >= 50,
        "holdout_expectancy_positive": float(holdout.get("expectancy_r") or -999.0) > 0.0,
        "holdout_pf_1_20_plus": float(holdout.get("profit_factor") or 0.0) >= 1.20,
        "ranked_expectancy_positive": float(ranked.get("expectancy_r") or -999.0) > 0.0,
        "ranked_pf_1_10_plus": float(ranked.get("profit_factor") or 0.0) >= 1.10,
    }
    return {
        "decision": "SHADOW_LIVE_CANDIDATE" if all(checks.values()) else "RESEARCH_ONLY",
        "checks": checks,
        "note": "Even a passing research gate should run in shadow mode before capital is allocated.",
    }


def merge_reports(shards):
    if not shards:
        raise RuntimeError("No V4 shard reports found.")

    expected = max(int(r.get("shard_count") or 1) for r in shards)
    found = {
        int(r.get("shard_index"))
        for r in shards
        if r.get("shard_index") is not None
    }
    if found != set(range(expected)):
        raise RuntimeError(
            f"Incomplete V4 shard set: expected={list(range(expected))} found={sorted(found)}"
        )

    manifest_ids = {str(r.get("manifest_id")) for r in shards}
    periods = {
        (str(r.get("period_start")), str(r.get("period_end")))
        for r in shards
    }
    if len(manifest_ids) != 1:
        raise RuntimeError(f"V4 manifest mismatch across shards: {sorted(manifest_ids)}")
    if len(periods) != 1:
        raise RuntimeError(f"V4 period mismatch across shards: {sorted(periods)}")

    first = shards[0]
    manifest = first.get("manifest") or {}
    frozen_symbols = list(manifest.get("symbols") or [])
    symbols = []
    trades = []
    errors = []
    source_shards = []

    for report in shards:
        symbols.extend(report.get("selected_symbols") or [])
        trades.extend(report.get("trades") or [])
        errors.extend(report.get("errors") or [])
        source_shards.append({
            "shard_index": report.get("shard_index"),
            "symbol_count": report.get("selected_symbol_count"),
            "candidates": len(report.get("trades") or []),
            "errors": len(report.get("errors") or []),
        })

    unique_symbols = sorted(set(symbols))
    integrity = {
        "ok": (
            len(symbols) == len(unique_symbols)
            and set(unique_symbols) == set(frozen_symbols)
            and len(shards) == expected
            and len(manifest_ids) == 1
            and len(periods) == 1
        ),
        "expected_shards": expected,
        "found_shards": len(shards),
        "manifest_ids": sorted(manifest_ids),
        "periods_identical": len(periods) == 1,
        "frozen_symbol_count": len(frozen_symbols),
        "merged_symbol_count": len(unique_symbols),
        "duplicate_shard_symbols": len(symbols) - len(unique_symbols),
        "missing_symbols": sorted(set(frozen_symbols) - set(unique_symbols)),
        "unexpected_symbols": sorted(set(unique_symbols) - set(frozen_symbols)),
    }
    if not integrity["ok"]:
        raise RuntimeError(f"V4 manifest integrity failed: {integrity}")

    trades = _dedupe(trades)
    walk_forward = apply_walkforward_meta(trades)
    ranked = rank_v4_entries(
        trades,
        max_per_timestamp=V4_MAX_PER_TIMESTAMP,
        max_concurrent=V4_MAX_CONCURRENT,
        max_per_cluster=V4_MAX_PER_CLUSTER,
    )
    calibration = build_v4_calibration(trades, ranked)
    portfolio = portfolio_metrics(
        ranked,
        starting_equity=V4_STARTING_EQUITY,
        risk_pct=V4_PORTFOLIO_RISK_PCT,
    )
    promotion = _promotion_gate(calibration, integrity)

    return {
        "engine": "Crypto Short V4 Probability-Driven Walk-Forward Backtest",
        "manifest_id": next(iter(manifest_ids)),
        "manifest": manifest,
        "manifest_integrity": integrity,
        "period_start": first.get("period_start"),
        "period_end": first.get("period_end"),
        "days": first.get("days"),
        "selected_symbols": unique_symbols,
        "selected_symbol_count": len(unique_symbols),
        "settings": {
            **(first.get("settings") or {}),
            "portfolio_rank": "out-of-sample expected_r",
            "meta_validation": "rolling walk-forward + final untouched holdout",
        },
        "walk_forward": walk_forward,
        "calibration": calibration,
        "v4_portfolio": portfolio,
        "promotion_gate": promotion,
        "trades": trades,
        "errors": errors,
        "shards": sorted(source_shards, key=lambda x: int(x["shard_index"])),
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "shard_outputs"
    shards = _load_shards(root)
    report = merge_reports(shards)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v4_backtest.json"), report)
    _write_trades_csv(os.path.join(OUTPUT_DIR, "v4_trades.csv"), report.get("trades") or [])
    _write_json(os.path.join(OUTPUT_DIR, "v4_calibration.json"), report.get("calibration") or {})
    _write_json(os.path.join(OUTPUT_DIR, "v4_manifest.json"), report.get("manifest") or {})
    with open(os.path.join(OUTPUT_DIR, "v4_summary.md"), "w", encoding="utf-8") as handle:
        handle.write(_summary_markdown(report))

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "manifest_integrity": report.get("manifest_integrity"),
        "symbols": report.get("selected_symbol_count"),
        "raw_candidates": (report.get("calibration") or {}).get("all_raw_candidates"),
        "entry_ready": (report.get("calibration") or {}).get("entry_ready"),
        "final_holdout_entry_ready": (report.get("calibration") or {}).get("final_holdout_entry_ready"),
        "ranked_portfolio": (report.get("calibration") or {}).get("ranked_portfolio"),
        "portfolio": report.get("v4_portfolio"),
        "promotion_gate": report.get("promotion_gate"),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
