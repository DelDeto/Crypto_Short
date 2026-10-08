"""V4.4.12 M2 shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4412_m2_backtest import run_v4412_m2_backtest
from .v4412_m2_config import V4412_STOP_ATR_VARIANTS

BASE_FIELDS = [
    "manifest_id", "symbol", "signal_time",
    "atr_1h", "current_price", "relative_4h_pct",
    "v428_trend_phase", "v428_structure_score",
    "v4412_m2_state", "v4412_m2_break_time",
    "v4412_m2_support_level", "v4412_m2_support_lower",
    "v4412_m2_support_upper",
    "v4412_m2_ready_reason", "v4412_m2_ready_time",
    "v4412_m2_watch_hours", "v4412_m2_failed_reclaim_attempts",
    "v4412_m2_retest_attempts", "v4412_m2_entry_selection_state",
    "v4412_m2_entry_time", "v4412_m2_entry",
    "v4412_m2_entry_below_support_atr", "v4412_m2_atr_at_entry",
]


def _fields():
    out = list(BASE_FIELDS)
    for s in V4412_STOP_ATR_VARIANTS:
        tag = str(s).replace(".", "_")
        p = f"v4412_m2_s{tag}"
        out += [
            f"{p}_{k}"
            for k in (
                "state", "stop_atr", "stop", "risk_atr", "risk_pct", "cost_r",
                "tp1_atr", "tp2_atr", "tp1_r", "tp2_r", "tp1", "tp2",
                "tp1_hit", "tp1_time", "tp2_hit", "tp2_time",
                "gross_r", "net_r", "hold_bars", "exit_time",
            )
        ]
    return out


CSV_FIELDS = _fields()


def main():
    report = run_v4412_m2_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v4412_m2_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v4412_m2_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "entries": sum(r.get("v4412_m2_entry_time") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
