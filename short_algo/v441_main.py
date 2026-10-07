"""V4.4.1 shard writer."""
import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v429_main import CSV_FIELDS as V429_FIELDS
from .v440_main import V440_FIELDS
from .v441_backtest import run_v441_backtest

M1_FIELDS = [
    "v441_m1_state", "v441_m1_context_ok", "v441_m1_confirm_score",
    "v441_m1_liquidity_pool", "v441_m1_liquidity_touches",
    "v441_m1_sweep_time", "v441_m1_sweep_high", "v441_m1_confirm_time",
    "v441_m1_failed_auction", "v441_m1_rejection", "v441_m1_micro_bos",
    "v441_m1_controlled_body", "v441_m1_no_reclaim", "v441_m1_confirm_body_atr",
    "v441_m1_entry_time", "v441_m1_entry", "v441_m1_stop",
    "v441_m1_risk_pct", "v441_m1_risk_atr", "v441_m1_cost_r",
    "v441_m1_demand_source", "v441_m1_demand_lower", "v441_m1_demand_upper",
    "v441_m1_demand_target", "v441_m1_room_r", "v441_m1_room_pass",
    "v441_m1_tp1", "v441_m1_tp2", "v441_m1_tp1_hit", "v441_m1_tp1_time",
    "v441_m1_ft_state", "v441_m1_ft_pass", "v441_m1_ft_mfe_r",
    "v441_m1_gross_r", "v441_m1_net_r", "v441_m1_hold_bars", "v441_m1_exit_time",
]

M2_FIELDS = [
    "v441_m2_state", "v441_m2_context_ok", "v441_m2_confirm_score",
    "v441_m2_support_level", "v441_m2_support_lower", "v441_m2_support_upper",
    "v441_m2_support_touches", "v441_m2_support_distance_atr",
    "v441_m2_pressure_score", "v441_m2_compression",
    "v441_m2_break_time", "v441_m2_break_body_atr", "v441_m2_controlled_break",
    "v441_m2_retest_touched", "v441_m2_retest_rejection", "v441_m2_acceptance_bars",
    "v441_m2_confirm_time", "v441_m2_entry_time", "v441_m2_entry", "v441_m2_stop",
    "v441_m2_risk_pct", "v441_m2_risk_atr", "v441_m2_cost_r",
    "v441_m2_demand_source", "v441_m2_demand_lower", "v441_m2_demand_upper",
    "v441_m2_demand_target", "v441_m2_room_r", "v441_m2_room_pass",
    "v441_m2_tp1", "v441_m2_tp2", "v441_m2_tp1_hit", "v441_m2_tp1_time",
    "v441_m2_ft_state", "v441_m2_ft_pass", "v441_m2_ft_mfe_r",
    "v441_m2_gross_r", "v441_m2_net_r", "v441_m2_hold_bars", "v441_m2_exit_time",
]

CSV_FIELDS = V429_FIELDS + V440_FIELDS + M1_FIELDS + M2_FIELDS


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _write_csv(path, rows, fields=CSV_FIELDS):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})


def main():
    report = run_v441_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v441_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v441_raw_candidates.csv"),
        report.get("trades") or [],
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "m1_contexts": sum(int(r.get("v441_m1_context_ok") or 0) for r in rows),
        "m1_fills": sum(r.get("v441_m1_net_r") is not None for r in rows),
        "m2_contexts": sum(int(r.get("v441_m2_context_ok") or 0) for r in rows),
        "m2_fills": sum(r.get("v441_m2_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
