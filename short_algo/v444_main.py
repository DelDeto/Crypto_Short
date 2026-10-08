"""V4.4.4 shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import CSV_FIELDS as V441_FIELDS, _write_csv, _write_json
from .v444_backtest import run_v444_backtest

V444_M2_FIELDS = [
    "v444_m2_state", "v444_m2_context_ok", "v444_m2_confirm_score",
    "v444_m2_support_level", "v444_m2_support_lower", "v444_m2_support_upper",
    "v444_m2_support_touches", "v444_m2_support_distance_atr",
    "v444_m2_pressure_score", "v444_m2_lower_highs",
    "v444_m2_close_compression", "v444_m2_near_support",
    "v444_m2_bearish_alignment", "v444_m2_relative_weakness",
    "v444_m2_recent_high_atr", "v444_m2_prior_high_atr",
    "v444_m2_recent_close_distance_atr", "v444_m2_prior_close_distance_atr",
    "v444_m2_break_time", "v444_m2_break_body_atr", "v444_m2_controlled_break",
    "v444_m2_retest_touched", "v444_m2_retest_rejection",
    "v444_m2_acceptance_bars", "v444_m2_confirm_time",
    "v444_m2_entry_below_support_atr",
    "v444_m2_entry_time", "v444_m2_entry", "v444_m2_stop",
    "v444_m2_risk_pct", "v444_m2_risk_atr", "v444_m2_cost_r",
    "v444_m2_demand_source", "v444_m2_demand_lower", "v444_m2_demand_upper",
    "v444_m2_demand_target", "v444_m2_room_r", "v444_m2_room_pass",
    "v444_m2_tp1", "v444_m2_tp2", "v444_m2_tp1_hit", "v444_m2_tp1_time",
    "v444_m2_ft_state", "v444_m2_ft_pass", "v444_m2_ft_mfe_r",
    "v444_m2_gross_r", "v444_m2_net_r", "v444_m2_hold_bars", "v444_m2_exit_time",
]

CSV_FIELDS = V441_FIELDS + V444_M2_FIELDS


def main():
    report = run_v444_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v444_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v444_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "m1_strict_fills": sum(r.get("v440_net_r") is not None for r in rows),
        "m1_scored_fills": sum(r.get("v441_m1_net_r") is not None for r in rows),
        "m2_old_fills": sum(r.get("v441_m2_net_r") is not None for r in rows),
        "m2_new_contexts": sum(int(r.get("v444_m2_context_ok") or 0) for r in rows),
        "m2_new_fills": sum(r.get("v444_m2_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
