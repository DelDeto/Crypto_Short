import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v41_backtest import run_v41_backtest


CSV_FIELDS = [
    "manifest_id", "symbol", "signal_time", "v3_engine", "v3_score",
    "entry_status", "entry_reject_reason", "entry_state_at_reject",
    "optimized_entry_filled", "zone_source",
    "zone_lower", "zone_upper", "zone_mid", "ideal_entry",
    "zone_prior_touch_count", "zone_age_1h_bars",
    "zone_location_quality", "zone_freshness_reason",
    "signal_entry", "signal_stop", "signal_tp1", "signal_stop_pct",
    "baseline_outcome", "baseline_realized_r", "baseline_cost_r",
    "baseline_mae_r", "baseline_mfe_r",
    "baseline_ft_1h_close_r", "baseline_ft_1h_mfe_r", "baseline_ft_1h_mae_r",
    "baseline_ft_4h_close_r", "baseline_ft_4h_mfe_r", "baseline_ft_4h_mae_r",
    "baseline_ft_first_0_5r_move",
    "baseline_post_sl_class", "baseline_post_sl_mfe_r",
    "entry_time", "exit_time", "entry", "stop", "stop_pct", "projected_cost_r", "tp1", "tp2",
    "support_room_r", "entry_improvement_atr", "confirmation_score",
    "wait_bars_15m", "touch_bar", "bos_bar", "bos_level",
    "structure_sequence", "outcome", "realized_r", "cost_r", "mae_r", "mfe_r",
    "bars_to_outcome", "ft_1h_close_r", "ft_1h_mfe_r", "ft_1h_mae_r",
    "ft_4h_close_r", "ft_4h_mfe_r", "ft_4h_mae_r",
    "ft_12h_close_r", "ft_24h_close_r", "ft_first_0_5r_move",
    "post_sl_class", "post_sl_reached_entry", "post_sl_reached_plus_1r",
    "post_sl_reached_tp2r", "post_sl_hours_to_entry",
    "post_sl_hours_to_plus_1r", "post_sl_hours_to_tp2r",
    "post_sl_mfe_r", "post_sl_additional_adverse_r",
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
    report = run_v41_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v41_backtest.json"), report)
    _write_csv(os.path.join(OUTPUT_DIR, "v41_trades.csv"), report.get("trades") or [])
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
