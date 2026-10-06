import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v424_backtest import run_v424_backtest
from .v424_model import FEATURE_NAMES


BASE_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "current_price", "atr_1h",
    "candidate_context_points",
    "setup_type", "setup_subtype",
    "zone_source",
    "preferred_zone_lower", "preferred_zone_upper",
    "zone_distance_atr",
    "severe_bottom_rule", "bottom_reasons",
    "reference_entry", "reference_stop", "reference_risk",
    "reference_tp1", "reference_tp2", "reference_runner",
    "fee_cost_r", "slippage_advisory_r",
    "slippage_is_hard_gate", "execution_note",
]

LABEL_FIELDS = [
    "y_4h_lower", "y_12h_lower", "y_first_short",
    "dir_1h_close_pct", "dir_1h_close_atr",
    "dir_1h_mfe_atr", "dir_1h_mae_atr", "dir_1h_short",
    "dir_4h_close_pct", "dir_4h_close_atr",
    "dir_4h_mfe_atr", "dir_4h_mae_atr", "dir_4h_short",
    "dir_12h_close_pct", "dir_12h_close_atr",
    "dir_12h_mfe_atr", "dir_12h_mae_atr", "dir_12h_short",
    "dir_first_0_5atr_move", "dir_short_votes", "dir_label",
]

CSV_FIELDS = BASE_FIELDS + FEATURE_NAMES + LABEL_FIELDS


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


def _write_csv(path, rows, fields=CSV_FIELDS):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: row.get(key)
                for key in fields
            })


def main():
    report = run_v424_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    _write_json(
        os.path.join(OUTPUT_DIR, "v424_backtest.json"),
        report,
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v424_raw_candidates.csv"),
        report.get("trades") or [],
    )

    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "shard_count": report.get("shard_count"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(report.get("trades") or []),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
