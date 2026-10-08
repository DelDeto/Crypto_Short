"""V4.4.8 M2-only shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v448_m2_backtest import run_v448_m2_backtest

CSV_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "atr_1h", "current_price", "relative_4h_pct",
    "v428_trend_phase", "v428_structure_score",
    "v448_m2_state", "v448_m2_lifecycle",
    "v448_m2_break_time", "v448_m2_break_body_atr",
    "v448_m2_support_level", "v448_m2_support_lower",
    "v448_m2_support_upper", "v448_m2_support_touches",
    "v448_m2_watch_state", "v448_m2_ready_reason",
    "v448_m2_ready_time", "v448_m2_watch_hours",
    "v448_m2_retest_attempts", "v448_m2_lower_high_confirmed",
    "v448_m2_entry_selection_state", "v448_m2_confirm_time",
    "v448_m2_entry_below_support_atr",
    "v448_m2_tactical_anchor", "v448_m2_hard_thesis_invalidation",
    "v448_m2_target_mode",
    "v448_m2_major_demand_source", "v448_m2_major_demand_lower",
    "v448_m2_major_demand_upper", "v448_m2_major_demand_touches",
    "v448_m2_major_demand_departure_atr", "v448_m2_major_demand_room_r",
    "v448_m2_entry_time", "v448_m2_entry", "v448_m2_stop",
    "v448_m2_risk_pct", "v448_m2_risk_atr", "v448_m2_cost_r",
    "v448_m2_room_r", "v448_m2_room_pass",
    "v448_m2_tp1", "v448_m2_tp2",
    "v448_m2_tp1_hit", "v448_m2_tp1_time",
    "v448_m2_tp2_hit", "v448_m2_tp2_time",
    "v448_m2_runner_target", "v448_m2_runner_room_r",
    "v448_m2_gross_r", "v448_m2_net_r",
    "v448_m2_hold_bars", "v448_m2_exit_time",
]


def main():
    report = run_v448_m2_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v448_m2_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v448_m2_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "break_events": sum(r.get("v448_m2_break_time") is not None for r in rows),
        "short_ready": sum(r.get("v448_m2_ready_time") is not None for r in rows),
        "entry_confirmed": sum(r.get("v448_m2_entry_selection_state") == "ENTRY" for r in rows),
        "open_space_plans": sum(r.get("v448_m2_target_mode") == "OPEN_SPACE" for r in rows),
        "major_demand_plans": sum(r.get("v448_m2_target_mode") == "MAJOR_4H_DEMAND" for r in rows),
        "fills": sum(r.get("v448_m2_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
