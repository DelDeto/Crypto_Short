"""M3 V1 shard writer."""
import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .m3_v1_backtest import run_m3_v1_backtest

CSV_FIELDS = [
    "symbol", "signal_time",
    "m3_market_state", "m3_market_r4_pct", "m3_market_r24_pct",
    "m3_state", "m3_tier",
    "m3_4h_bear_score", "m3_4h_below_ema20", "m3_4h_ema_bear",
    "m3_4h_structure_bear",
    "m3_impulse_atr", "m3_pullback_retrace", "m3_pullback_bars",
    "m3_impulse_peak_time", "m3_impulse_trough_time",
    "m3_impulse_peak", "m3_impulse_trough",
    "m3_resistance_source", "m3_resistance", "m3_resistance_distance_atr",
    "m3_ema20_distance_atr", "m3_failed_reclaim",
    "m3_bearish_rejection", "m3_lower_high_proxy",
    "m3_rejection_quality_points", "m3_confirmation_state",
    "m3_strong_15m_bos", "m3_confirm_time", "m3_entry_time",
    "m3_entry", "m3_stop", "m3_risk_atr", "m3_risk_pct", "m3_atr",
    "m3_t1_0_state", "m3_t1_0_target", "m3_t1_0_target_r",
    "m3_t1_0_cost_r", "m3_t1_0_gross_r", "m3_t1_0_net_r",
    "m3_t1_0_hold_bars", "m3_t1_0_exit_time", "m3_t1_0_mfe_r", "m3_t1_0_mae_r",
    "m3_t1_5_state", "m3_t1_5_target", "m3_t1_5_target_r",
    "m3_t1_5_cost_r", "m3_t1_5_gross_r", "m3_t1_5_net_r",
    "m3_t1_5_hold_bars", "m3_t1_5_exit_time", "m3_t1_5_mfe_r", "m3_t1_5_mae_r",
    "m3_t2_0_state", "m3_t2_0_target", "m3_t2_0_target_r",
    "m3_t2_0_cost_r", "m3_t2_0_gross_r", "m3_t2_0_net_r",
    "m3_t2_0_hold_bars", "m3_t2_0_exit_time", "m3_t2_0_mfe_r", "m3_t2_0_mae_r",
]


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in CSV_FIELDS})


def main():
    report = run_m3_v1_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "m3_v1_backtest.json"), report)
    rows = report.get("candidates") or []
    _write_csv(os.path.join(OUTPUT_DIR, "m3_v1_candidates.csv"), rows)

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "candidates": len(rows),
        "tier_A": sum(r.get("m3_tier") == "A" for r in rows),
        "tier_B": sum(r.get("m3_tier") == "B" for r in rows),
        "tier_C": sum(r.get("m3_tier") == "C" for r in rows),
        "benchmark_entries": sum(
            r.get("m3_state") == "ENTRY_BENCHMARK" for r in rows
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
