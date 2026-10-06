import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v422_backtest import run_v422_backtest


CSV_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "v422_bias", "v422_action", "v422_score",
    "v422_thesis", "v422_subtype",
    "directional_score", "location_score", "trigger_score",
    "bottom_risk", "rebound_risk", "anti_bottom_total",
    "bottom_reasons",
    "continuation_pullback_ready",
    "continuation_pullback_reason",
    "relative_4h_pct", "relative_24h_pct",
    "current_price", "atr_1h",
    "zone_source",
    "preferred_zone_lower", "preferred_zone_upper",
    "preferred_zone_distance_atr",
    "return_4h_pct", "return_12h_pct", "return_24h_pct",
    "below_ema20_atr",
    "distance_12h_low_atr", "distance_24h_low_atr",
    "drop_leg_12h_atr", "fast_drop_3h_atr",
    "range_position_24h", "support_distance_atr",
    "last_range_atr", "last_lower_wick_ratio",
    "volume_ratio_1h",
    "reference_entry", "reference_stop", "reference_risk",
    "reference_tp1", "reference_tp2", "reference_runner",
    "fee_cost_r", "slippage_advisory_r",
    "slippage_is_hard_gate", "execution_note",
    "dir_1h_close_pct", "dir_1h_close_atr",
    "dir_1h_mfe_atr", "dir_1h_mae_atr", "dir_1h_short",
    "dir_4h_close_pct", "dir_4h_close_atr",
    "dir_4h_mfe_atr", "dir_4h_mae_atr", "dir_4h_short",
    "dir_12h_close_pct", "dir_12h_close_atr",
    "dir_12h_mfe_atr", "dir_12h_mae_atr", "dir_12h_short",
    "dir_first_0_5atr_move", "dir_short_votes", "dir_label",
]


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: row.get(key)
                for key in CSV_FIELDS
            })


def main():
    report = run_v422_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(
        os.path.join(OUTPUT_DIR, "v422_backtest.json"),
        report,
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v422_candidates.csv"),
        report.get("trades") or [],
    )

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "shard_count": report.get("shard_count"),
        "symbols": report.get("selected_symbol_count"),
        "candidates": len(report.get("trades") or []),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
