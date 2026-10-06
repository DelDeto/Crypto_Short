import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v42_backtest import run_v42_backtest


CSV_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "v42_setup", "v42_subtype", "v42_setup_quality",
    "zone_source", "zone_lower", "zone_upper",
    "zone_location_quality", "zone_prior_touch_count",
    "entry_status", "entry_reject_reason",
    "optimized_entry_filled", "shadow_execution_candidate",
    "audit_zone_touched", "audit_meaningful_pivot_found",
    "audit_displacement_bos", "audit_retest_seen",
    "audit_failed_retest_confirmed",
    "baseline_entry", "baseline_stop", "baseline_outcome",
    "baseline_realized_r", "baseline_cost_r",
    "baseline_ft_1h_close_r", "baseline_ft_4h_close_r",
    "baseline_ft_first_0_5r_move", "baseline_post_sl_class",
    "shadow_entry_time", "shadow_entry", "shadow_stop",
    "shadow_stop_pct", "shadow_support_room_r",
    "shadow_projected_cost_r", "shadow_bos_level",
    "shadow_pivot_age_bars", "shadow_pivot_prominence_atr15",
    "shadow_outcome", "shadow_realized_r", "shadow_cost_r",
    "shadow_ft_1h_close_r", "shadow_ft_4h_close_r",
    "shadow_ft_12h_close_r", "shadow_ft_24h_close_r",
    "shadow_ft_first_0_5r_move", "shadow_post_sl_class",
    "entry_time", "entry", "stop", "stop_pct",
    "support_room_r", "projected_cost_r",
    "tp1", "tp2", "runner", "bos_level",
    "pivot_age_bars", "pivot_prominence_atr15",
    "wait_bars_15m", "outcome", "realized_r", "cost_r",
    "mae_r", "mfe_r", "bars_to_outcome",
    "ft_1h_close_r", "ft_4h_close_r", "ft_12h_close_r",
    "ft_24h_close_r", "ft_first_0_5r_move",
    "post_sl_class", "post_sl_reached_entry",
    "post_sl_reached_plus_1r", "post_sl_reached_tp2r",
]


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in CSV_FIELDS})


def main():
    report = run_v42_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v42_backtest.json"), report)
    _write_csv(os.path.join(OUTPUT_DIR, "v42_trades.csv"), report.get("trades") or [])
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "shard_count": report.get("shard_count"),
        "symbols": report.get("selected_symbol_count"),
        "setups": len(report.get("trades") or []),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
