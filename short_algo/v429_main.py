import csv
import json
import os
import sys

from .config import OUTPUT_DIR
from .v428_main import CSV_FIELDS as V428_CSV_FIELDS
from .v429_backtest import run_v429_backtest


DIAG_FIELDS = [
    "ft_first_0_5r_move",
    "ft_close_r_1h", "ft_close_r_4h", "ft_close_r_12h", "ft_close_r_24h",
    "ft_mfe_r_4h", "ft_mae_r_4h", "ft_mfe_r_24h", "ft_mae_r_24h",
    "post_sl_class", "post_sl_reclaim_entry", "post_sl_plus_1r",
    "post_sl_plus_2r", "post_sl_mfe_r", "post_sl_additional_adverse_r",
]
CSV_FIELDS = V428_CSV_FIELDS + DIAG_FIELDS


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as h:
        json.dump(payload, h, ensure_ascii=False, indent=2, default=str)


def _write_csv(path, rows, fields=CSV_FIELDS):
    with open(path, "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})


def main():
    report = run_v429_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v429_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v429_raw_candidates.csv"),
        report.get("trades") or [],
    )
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(report.get("trades") or []),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
