"""V4.4.3 60-day shard writer.

The underlying execution replay is the V4.4.1 causal engine. V4.4.3 changes
only post-replay research cohorts built from signal-time fields.
"""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_backtest import run_v441_backtest
from .v441_main import CSV_FIELDS, _write_csv, _write_json


def main():
    report = run_v441_backtest()
    report["engine"] = "Crypto Short V4.4.3 60d Episode + M2 Funnel Research"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v443_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v443_raw_candidates.csv"),
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
