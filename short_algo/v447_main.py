"""V4.4.7 shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v444_main import CSV_FIELDS as V444_FIELDS
from .v447_backtest import run_v447_backtest

PERSISTENT_FIELDS = [
    "v447_m2_state",
    "v447_m2_context_ok",
    "v447_m2_lifecycle",
    "v447_m2_break_time",
    "v447_m2_break_body_atr",
    "v447_m2_support_level",
    "v447_m2_support_lower",
    "v447_m2_support_upper",
    "v447_m2_support_touches",
    "v447_m2_watch_state",
    "v447_m2_ready_reason",
    "v447_m2_ready_time",
    "v447_m2_watch_hours",
    "v447_m2_retest_attempts",
    "v447_m2_bars_below",
    "v447_m2_max_reclaim_high",
    "v447_m2_lower_high_confirmed",
    "v447_m2_entry_selection_state",
    "v447_m2_confirm_time",
    "v447_m2_entry_below_support_atr",
    "v447_m2_entry_time",
    "v447_m2_entry",
    "v447_m2_stop",
    "v447_m2_risk_pct",
    "v447_m2_risk_atr",
    "v447_m2_cost_r",
    "v447_m2_demand_source",
    "v447_m2_demand_lower",
    "v447_m2_demand_upper",
    "v447_m2_demand_target",
    "v447_m2_room_r",
    "v447_m2_room_pass",
    "v447_m2_tp1",
    "v447_m2_tp2",
    "v447_m2_tp1_hit",
    "v447_m2_tp1_time",
    "v447_m2_ft_state",
    "v447_m2_ft_pass",
    "v447_m2_ft_mfe_r",
    "v447_m2_gross_r",
    "v447_m2_net_r",
    "v447_m2_hold_bars",
    "v447_m2_exit_time",
]

CSV_FIELDS = V444_FIELDS + PERSISTENT_FIELDS


def main():
    report = run_v447_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v447_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v447_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "m1a_fills": sum(
            r.get("v440_net_r") is not None for r in rows
        ),
        "m1b_fills": sum(
            r.get("v441_m1_net_r") is not None for r in rows
        ),
        "m2_v444_fills": sum(
            r.get("v444_m2_net_r") is not None for r in rows
        ),
        "m2_breaks": sum(
            r.get("v447_m2_break_time") is not None for r in rows
        ),
        "m2_short_ready": sum(
            r.get("v447_m2_ready_time") is not None for r in rows
        ),
        "m2_persistent_fills": sum(
            r.get("v447_m2_net_r") is not None for r in rows
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
