"""V4.4 shard writer."""
import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v429_main import CSV_FIELDS as V429_FIELDS
from .v440_backtest import run_v440_backtest

SUPPORT_FIELDS = [
    "v430_support_minor",
    "v430_support_intermediate",
    "v430_support_structural",
    "v430_structural_room_r",
    "v430_minor_room_r",
    "v430_support_class",
    "v430_support_pass",
    "v430_1h_pivot_count",
    "v430_4h_pivot_count",
]

A2_FIELDS = [
    "v431_A2_state", "v431_A2_trigger", "v431_A2_trigger_time",
    "v431_A2_entry_time", "v431_A2_entry", "v431_A2_stop",
    "v431_A2_tp2", "v431_A2_risk_pct", "v431_A2_risk_atr",
    "v431_A2_cost_r", "v431_A2_gross_r", "v431_A2_net_r",
    "v431_A2_hold_bars", "v431_A2_exit_time",
    "v431_A2_structural_room_r", "v431_A2_structural_room_pass",
    "v431_A2_ft_first_0_5r", "v431_A2_mfe_r_1h", "v431_A2_mae_r_1h",
    "v431_A2_mfe_r_4h", "v431_A2_mae_r_4h",
]

V440_FIELDS = [
    "v440_state", "v440_trigger", "v440_liquidity_pool",
    "v440_liquidity_touches", "v440_sweep_time", "v440_sweep_high",
    "v440_bos_time", "v440_bos_level", "v440_break_body_atr",
    "v440_entry_time", "v440_entry", "v440_stop", "v440_risk_pct",
    "v440_risk_atr", "v440_cost_r", "v440_demand_source",
    "v440_demand_lower", "v440_demand_upper", "v440_demand_target",
    "v440_room_r", "v440_room_pass", "v440_tp1", "v440_tp2",
    "v440_tp1_hit", "v440_tp1_time", "v440_ft_state", "v440_ft_pass",
    "v440_ft_mfe_r", "v440_gross_r", "v440_net_r", "v440_hold_bars",
    "v440_exit_time",
]

CSV_FIELDS = V429_FIELDS + SUPPORT_FIELDS + A2_FIELDS + V440_FIELDS


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
    report = run_v440_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v440_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v440_raw_candidates.csv"),
        report.get("trades") or [],
    )
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(report.get("trades") or []),
        "v440_fills": sum(
            1 for r in report.get("trades") or []
            if r.get("v440_net_r") is not None
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
