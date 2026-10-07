"""V4.3.1 shard writer."""
import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v429_main import CSV_FIELDS as V429_FIELDS
from .v431_backtest import run_v431_backtest

SUPPORT_FIELDS = [
    "v430_support_minor",
    "v430_support_intermediate",
    "v430_support_structural",
    "v430_structural_room_r",
    "v430_minor_room_r",
    "v430_support_class",
    "v430_support_pass",
    "v430_1h_pivot_count",
    "v430_4h_pivot_count",
]

MODE_SUFFIXES = [
    "state", "trigger", "trigger_time", "entry_time", "entry", "stop", "tp2",
    "risk_pct", "risk_atr", "cost_r", "gross_r", "net_r", "hold_bars",
    "exit_time", "exit_bar_index", "wait_bars", "entry_improvement_atr",
    "entry_vs_reference_atr", "structural_room_r", "structural_room_pass",
    "ft_first_0_5r", "mfe_r_1h", "mae_r_1h", "mfe_r_4h", "mae_r_4h",
]
MODES = ["A0", "A1", "A2", "A3", "A0C", "A1C", "A2C", "A3C"]
EXEC_FIELDS = [
    f"v431_{mode}_{suffix}"
    for mode in MODES
    for suffix in MODE_SUFFIXES
]
for mode in ("A0", "A1", "A2", "A3"):
    EXEC_FIELDS += [
        f"v431_{mode}_plus_C_net_r",
        f"v431_{mode}_plus_C_trades",
        f"v431_{mode}_plus_C_state",
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
    report = run_v431_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v431_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v431_raw_candidates.csv"),
        report.get("trades") or [],
    )
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(report.get("trades") or []),
        "one_hour_confirmed": sum(
            int(r.get("v428_entry_confirmed") or 0)
            for r in report.get("trades") or []
        ),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
