"""V4.4.8 M1-only shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json, CSV_FIELDS
from .v448_m1_backtest import run_v448_m1_backtest


def main():
    report = run_v448_m1_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v448_m1_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v448_m1_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "m1a_terminal": sum(r.get("v440_net_r") is not None for r in rows),
        "m1b_terminal": sum(r.get("v441_m1_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
