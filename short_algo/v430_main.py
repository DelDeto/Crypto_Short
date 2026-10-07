"""V4.3.0 shard output. CSV preserves all A/B/C execution fields."""
import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v429_main import CSV_FIELDS as V429_FIELDS
from .v430_backtest import run_v430_backtest

SUPPORT_FIELDS = [
    "v430_support_minor", "v430_support_intermediate",
    "v430_support_structural", "v430_structural_room_r",
    "v430_minor_room_r", "v430_support_class",
    "v430_support_pass", "v430_1h_pivot_count", "v430_4h_pivot_count",
]
EXEC_FIELDS = []
for _mode in ("A", "B", "C"):
    EXEC_FIELDS += [
        f"v430_{_mode}_state", f"v430_{_mode}_entry_time",
        f"v430_{_mode}_entry", f"v430_{_mode}_stop",
        f"v430_{_mode}_tp2", f"v430_{_mode}_risk_pct",
        f"v430_{_mode}_gross_r", f"v430_{_mode}_cost_r",
        f"v430_{_mode}_net_r", f"v430_{_mode}_hold_bars",
        f"v430_{_mode}_exit_time", f"v430_{_mode}_exit_bar_index",
        f"v430_{_mode}_wait_bars",
    ]
EXEC_FIELDS += [
    "v430_B_pullback_level", "v430_C_reclaim_level",
    "v430_AplusC_net_r", "v430_AplusC_trades", "v430_AplusC_state",
]
CSV_FIELDS = V429_FIELDS + SUPPORT_FIELDS + EXEC_FIELDS


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _write_csv(path, rows, fields=CSV_FIELDS):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})


def main():
    report = run_v430_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v430_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v430_raw_candidates.csv"),
        report.get("trades") or [],
    )
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(report.get("trades") or []),
        "confirmed": sum(int(r.get("v428_entry_confirmed") or 0) for r in report.get("trades") or []),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
