"""M3 V3.2 shard writer."""
import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .m3_v32_backtest import run_m3_v32_backtest

FIELDS = [
    "symbol","signal_time","m3v32_market_state",
    "m3v2_poi_source","m3v2_entry_time","m3v2_entry",
    "m3v21_retest_quality_score","m3v21_retest_penetration_atr15",
    "m3v21_retest_upper_wick_ratio","m3v21_retest_lower_high",
    "m3v21_retest_volume_vs_displacement","m3v2_target3_atr",
    "m3v32_core_gate_pass","m3v32_tight_gate_pass","m3v32_trigger_state",
    "m3v32_trigger_time","m3v32_entry_time","m3v32_entry",
    "m3v32_trigger_chase_atr15","m3v32_trigger_wait_bars",
    "m3v32_hit_3pct_24h","m3v32_minutes_to_3pct","m3v32_pre3pct_mae_pct",
    "m3v32_clean3_adverse_0_5","m3v32_clean3_adverse_0_75","m3v32_clean3_adverse_1_0",
    "m3v32_max_favorable_pct_24h","m3v32_max_adverse_pct_24h",
]


def main():
    report = run_m3_v32_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "m3_v32_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUTPUT_DIR, "m3_v32_rows.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow({k: row.get(k) for k in FIELDS})

    print(json.dumps({
        "manifest_id": report["manifest_id"],
        "shard": report["shard_index"],
        "symbols": report["selected_symbol_count"],
        "rows": len(report["rows"]),
        "errors": len(report["errors"]),
    }, indent=2))
    return 0 if report["selected_symbol_count"] else 2


if __name__ == "__main__":
    sys.exit(main())
