"""V4.4.2 60-day shard writer.

Reuses V4.4.1 causal replay exactly; V4.4.2 changes only the validation
cohorts/quality filters applied by v442_merge.
"""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_backtest import run_v441_backtest
from .v441_main import CSV_FIELDS, _write_csv, _write_json


def main():
    report = run_v441_backtest()
    report["engine"] = "Crypto Short V4.4.2 60d Quality-Tier Research"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v442_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v442_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "engine": report["engine"],
        "days": report.get("days"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
