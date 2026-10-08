"""V4.4.9 M2-only shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v449_m2_backtest import run_v449_m2_backtest

CSV_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "atr_1h", "current_price", "relative_4h_pct",
    "v428_trend_phase", "v428_structure_score",
    "v449_m2_state", "v449_m2_lifecycle",
    "v449_m2_break_time", "v449_m2_break_body_atr",
    "v449_m2_support_level", "v449_m2_support_lower",
    "v449_m2_support_upper", "v449_m2_support_touches",
    "v449_m2_watch_state", "v449_m2_ready_reason",
    "v449_m2_ready_time", "v449_m2_watch_hours",
    "v449_m2_failed_reclaim_attempts", "v449_m2_retest_attempts",
    "v449_m2_pivot_high_count",
    "v449_m2_flip_anchor_high", "v449_m2_prior_flip_high",
    "v449_m2_entry_selection_state", "v449_m2_confirm_time",
    "v449_m2_entry_below_support_atr",
    "v449_m2_tactical_anchor", "v449_m2_hard_thesis_invalidation",
    "v449_m2_major_demand_source", "v449_m2_major_demand_lower",
    "v449_m2_major_demand_upper", "v449_m2_major_demand_touches",
    "v449_m2_major_demand_departure_atr", "v449_m2_major_demand_room_r",
    "v449_m2_major_demand_obstacle",
    "v449_m2_entry_time", "v449_m2_entry", "v449_m2_stop",
    "v449_m2_risk_pct", "v449_m2_risk_atr", "v449_m2_cost_r",
    "v449_m2_room_r", "v449_m2_room_pass",
    "v449_m2_tp1", "v449_m2_tp2",
    "v449_m2_tp1_hit", "v449_m2_tp1_time",
    "v449_m2_tp2_hit", "v449_m2_tp2_time",
    "v449_m2_runner_target", "v449_m2_runner_room_r",
    "v449_m2_gross_r", "v449_m2_net_r",
    "v449_m2_hold_bars", "v449_m2_exit_time",
]


def main():
    report = run_v449_m2_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v449_m2_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v449_m2_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "break_events": sum(
            r.get("v449_m2_break_time") is not None for r in rows
        ),
        "confirmed_flips": sum(
            r.get("v449_m2_ready_time") is not None for r in rows
        ),
        "entry_confirmed": sum(
            r.get("v449_m2_entry_selection_state") == "ENTRY" for r in rows
        ),
        "fills": sum(r.get("v449_m2_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
