"""V4.4.10 M2 Entry Path Study shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4410_m2_backtest import run_v4410_m2_backtest
from .v4410_m2_config import (
    V4410_FAVORABLE_THRESHOLDS_ATR,
    V4410_PATH_HORIZONS_HOURS,
)


BASE_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "atr_1h", "current_price", "relative_4h_pct",
    "v428_trend_phase", "v428_structure_score",
    "v4410_m2_state", "v4410_m2_lifecycle",
    "v4410_m2_break_time",
    "v4410_m2_support_level", "v4410_m2_support_lower",
    "v4410_m2_support_upper",
    "v4410_m2_watch_state", "v4410_m2_ready_reason",
    "v4410_m2_ready_time", "v4410_m2_watch_hours",
    "v4410_m2_failed_reclaim_attempts",
    "v4410_m2_retest_attempts",
    "v4410_m2_entry_selection_state",
    "v4410_m2_entry_time", "v4410_m2_entry",
    "v4410_m2_entry_below_support_atr", "v4410_m2_atr_at_entry",
    "v4410_m2_reclaimed_after_entry", "v4410_m2_reclaim_time",
    "v4410_m2_time_to_reclaim_h",
    "v4410_m2_max_close_above_zone_atr",
]


def _path_fields():
    fields = list(BASE_FIELDS)
    for hours in V4410_PATH_HORIZONS_HOURS:
        tag = f"{int(hours)}h"
        for key in (
            "complete", "bars", "mae_atr", "mae_pct",
            "mfe_atr", "mfe_pct", "time_to_mae_h", "time_to_mfe_h",
            "forward_close_atr", "forward_close_pct",
        ):
            fields.append(f"v4410_m2_{tag}_{key}")

    for threshold in V4410_FAVORABLE_THRESHOLDS_ATR:
        tag = str(threshold).replace(".", "_")
        for key in (
            "complete", "hit", "time_to_hit_h",
            "mae_before_hit_atr", "mae_before_hit_pct",
        ):
            fields.append(f"v4410_m2_fav_{tag}atr_{key}")
    return fields


CSV_FIELDS = _path_fields()


def main():
    report = run_v4410_m2_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(
        os.path.join(OUTPUT_DIR, "v4410_m2_backtest.json"),
        report,
    )
    _write_csv(
        os.path.join(OUTPUT_DIR, "v4410_m2_path_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )

    rows = report.get("trades") or []
    entries = [
        r for r in rows if r.get("v4410_m2_entry_time") is not None
    ]
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "break_events": sum(
            r.get("v4410_m2_break_time") is not None for r in rows
        ),
        "confirmed_flips": sum(
            r.get("v4410_m2_ready_time") is not None for r in rows
        ),
        "entries": len(entries),
        "path_168h_complete": sum(
            int(r.get("v4410_m2_168h_complete") or 0) for r in entries
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
