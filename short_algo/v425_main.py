import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v425_backtest import run_v425_backtest
from .v425_model import FEATURE_NAMES


PATH_FIELDS = []
for h in (1, 2, 4, 8, 12, 16, 20, 24):
    PATH_FIELDS += [
        f"dir_{h}h_close_pct",
        f"dir_{h}h_close_atr",
        f"dir_{h}h_mfe_atr",
        f"dir_{h}h_mae_atr",
        f"dir_{h}h_short",
        f"market_{h}h_return_pct",
        f"relative_{h}h_future_pct",
    ]

BLOCK_FIELDS = []
for start in (0, 4, 8, 12, 16, 20):
    end = start + 4
    BLOCK_FIELDS += [
        f"block_{start}_{end}h_return_atr",
        f"block_{start}_{end}h_mfe_atr",
        f"block_{start}_{end}h_mae_atr",
        f"block_{start}_{end}h_short",
        f"block_{start}_{end}h_relative_pct",
    ]

BASE_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "current_price", "atr_1h",
    "candidate_context_points",
    "setup_type", "setup_subtype", "zone_source",
    "preferred_zone_lower", "preferred_zone_upper",
    "zone_distance_atr", "severe_bottom_rule", "bottom_reasons",
    "reference_entry", "reference_stop", "reference_risk",
    "reference_tp1", "reference_tp2", "reference_runner",
    "fee_cost_r", "slippage_advisory_r",
    "slippage_is_hard_gate", "execution_note",
]

LABEL_FIELDS = [
    "y_4h_lower", "y_12h_lower", "y_24h_lower", "y_first_short",
    "y_rel_4h_underperform", "y_rel_12h_underperform",
    "y_rel_24h_underperform",
    "dir_first_0_5atr_move", "dir_short_votes_24h",
    "max_downside_24h_atr", "max_adverse_24h_atr",
    "hours_to_max_downside", "hours_to_max_adverse",
    "reclaimed_signal_after_mfe", "rebound_from_mfe_atr",
    "hours_mfe_to_signal_reclaim", "path_class_24h",
]

CSV_FIELDS = (
    BASE_FIELDS
    + FEATURE_NAMES
    + LABEL_FIELDS
    + PATH_FIELDS
    + BLOCK_FIELDS
)


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
    report = run_v425_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(
        os.path.join(OUTPUT_DIR, "v425_backtest.json"),
        report,
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v425_raw_candidates.csv"),
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
