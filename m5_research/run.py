"""M5 V0.1 CLI: bounded historical MEXC futures event discovery.

Output is strictly historical exploratory observations and audit material,
not outcome studies, forward-confirmation, ranking, recommendations or orders.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import traceback
import pandas as pd

from .config import (EVENTS, MIN_CANDLE_COVERAGE, WARMUP_BARS,
                     RESEARCH_ONLY)
from .data import (STEP, completed_window, coverage, record_catalogue,
                   request_candles, select_universe)
from .events import discover_events, features_asof

def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def run(days=14, shards=16, shard_index=0, max_symbols=12, full_shard=False,
        outdir=Path("output/m5_research"), now=None,
        catalogue_fn=record_catalogue, fetch_fn=request_candles):
    if full_shard and max_symbols != 0:
        # full_shard controls deliberate all-symbol workload; limit=0 is unbounded.
        max_symbols = 0
    if not full_shard and not 1 <= max_symbols <= 50:
        raise ValueError("Bounded exploratory mode requires 1..50 symbols")
    start, end = completed_window(now, days)
    # Need 128 completely observed predecessor candles for every signal.
    fetch_start = start - WARMUP_BARS * STEP
    symbols, cat_audit = catalogue_fn()
    symbols = sorted(set(symbols))
    if not symbols or "BTC_USDT" not in symbols:
        raise RuntimeError("Missing MEXC BTC futures or empty universe")
    selected = select_universe(symbols, shards, shard_index, 0 if full_shard else max_symbols)
    batch = end.strftime("%Y%m%dT%H%MZ")
    outdir = Path(outdir) / batch / f"shard-{shard_index:02d}-of-{shards:02d}"
    outdir.mkdir(parents=True, exist_ok=True)
    inventory = {
        "engine": "M5 V0.1 exploratory historical event discovery",
        "research_only": RESEARCH_ONLY,
        "no_orders": True, "no_short_signals": True, "no_future_outcome_labels": True,
        "historical_not_forward": True,
        "exchange": "MEXC futures", "timeframe": "15m with causal rolling 1h/4h context",
        "requested_days": days,
        "first_research_bar_open_utc": start.isoformat(),
        "last_closed_bar_open_utc": end.isoformat(),
        "source_study_universe": "CURRENT_LIVE_CATALOGUE_SURVIVORSHIP_BIAS_WARNING",
        "catalogue_count": len(symbols),
        "catalogue_sha256": hashlib.sha256("\n".join(symbols).encode()).hexdigest(),
        "catalogue_audit": cat_audit,
        "shards": shards, "shard_index": shard_index,
        "sample_limit": 0 if full_shard else max_symbols,
        "selected_count": len(selected),
        "selected_symbols": selected,
        "all_eight_event_ids": list(EVENTS),
        "matching_scope": "WITHIN_SHARD_PRELIMINARY",
        "data_coverage_gate": MIN_CANDLE_COVERAGE,
        "status": "RUNNING",
    }
    _write_json(outdir / "manifest.json", inventory)
    # BTC is external context, not counted as an observed member of every shard.
    btc, requests = fetch_fn("BTC_USDT", fetch_start, end)
    if coverage(btc, start, end) < MIN_CANDLE_COVERAGE:
        raise RuntimeError("BTC context incomplete: stop rather than produce biased E07")
    features = []
    rejected = {}
    accepted = {}
    rawdir = outdir / "candles"
    rawdir.mkdir(exist_ok=True)
    for pos, symbol in enumerate(selected, 1):
        try:
            if symbol == "BTC_USDT":
                frame, n = btc, 0
            else:
                frame, n = fetch_fn(symbol, fetch_start, end)
            requests += n
            ratio = coverage(frame, start, end)
            if ratio < MIN_CANDLE_COVERAGE:
                rejected[symbol] = {"reason": "LOW_15M_COVERAGE", "coverage": ratio}
                print(f"[M5] {pos}/{len(selected)} {symbol}: coverage {ratio} excluded", flush=True)
                continue
            f = features_asof(symbol, frame, btc, start)
            eligible = int(f["quality_ready"].sum()) if not f.empty else 0
            if eligible == 0:
                rejected[symbol] = {"reason": "NO_CLEAN_ASOF_WINDOWS", "coverage": ratio}
                continue
            features.append(f)
            accepted[symbol] = {"coverage": ratio, "asof_ready_bars": eligible}
            frame.to_csv(rawdir / f"{symbol}.csv.gz", compression="gzip")
            print(f"[M5] {pos}/{len(selected)} {symbol}: {eligible} causal bars", flush=True)
        except Exception as exc:
            rejected[symbol] = {"reason": "FETCH_OR_FEATURE_FAILURE", "message": str(exc)[:180]}
            print(f"[M5] {pos}/{len(selected)} {symbol}: ERROR {str(exc)[:160]}", flush=True)

    event_rows, event_counts, asof_rows = discover_events(features)
    with gzip.open(outdir / "event_registry.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in event_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    inventory.update({
        "status": "EXPLORATORY_COMPLETE" if accepted else "NO_USABLE_SYMBOLS",
        "accepted_symbol_count": len(accepted),
        "rejected_symbol_count": len(rejected),
        "accepted_summary": accepted,
        "rejected_summary": rejected,
        "http_attempt_count": requests,
        "asof_feature_rows": asof_rows,
        "event_counts": event_counts,
        "event_count_all_families": len(event_rows),
        "matched_control_events": sum(bool(r["control_count"]) for r in event_rows),
        "events_no_controls": sum(r["control_count"] == 0 for r in event_rows),
        "overlap_can_exist_across_families": True,
        "outcomes_computed": False,
        "inference_or_edge_claims": False,
        "warning": ("Controls are selected only among members of THIS shard; "
                    "not an all-market matched control sample. "
                    "Live catalogue excludes delisted coins; older days may have survivorship bias. "
                    "Historical event observations are not prospective forward evidence."),
    })
    _write_json(outdir / "manifest.json", inventory)
    print(json.dumps({k:inventory[k] for k in (
        "status", "catalogue_count", "selected_count",
        "accepted_symbol_count", "rejected_symbol_count",
        "http_attempt_count", "event_counts", "event_count_all_families",
        "matched_control_events", "events_no_controls")}, ensure_ascii=False, indent=2))
    print("OUTPUT_DIRECTORY=" + str(outdir))
    return inventory

def main():
    parser = argparse.ArgumentParser(description="M5 historical research, never live orders")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--shards", type=int, default=16)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--max-symbols", type=int, default=12)
    parser.add_argument("--full-shard", action="store_true")
    parser.add_argument("--outdir", type=Path, default=Path("output/m5_research"))
    args = parser.parse_args()
    result = run(days=args.days, shards=args.shards, shard_index=args.shard_index,
                 max_symbols=args.max_symbols, full_shard=args.full_shard,
                 outdir=args.outdir)
    return 0 if result["status"] == "EXPLORATORY_COMPLETE" else 2

if __name__ == "__main__":
    raise SystemExit(main())
