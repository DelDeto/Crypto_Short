"""V4.4.6 shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v444_main import CSV_FIELDS as V444_FIELDS
from .v446_backtest import run_v446_backtest

EVENT_FIELDS = [
    "v446_m2_event_found",
    "v446_m2_event_break_time",
    "v446_m2_event_support",
    "v446_m2_event_support_touches",
    "v446_m2_event_pressure_score",
    "v446_m2_event_break_body_atr",
]

VARIANT_FIELDS = []
for _p in ("v446_m2_r1", "v446_m2_r2"):
    VARIANT_FIELDS += [
        f"{_p}_state", f"{_p}_context_ok", f"{_p}_mode",
        f"{_p}_break_time", f"{_p}_support_level", f"{_p}_support_touches",
        f"{_p}_pressure_score", f"{_p}_selection_state", f"{_p}_early_retest",
        f"{_p}_retest_time", f"{_p}_retest_bars_after_break",
        f"{_p}_acceptance_closes", f"{_p}_pre_extension_atr",
        f"{_p}_entry_below_support_atr", f"{_p}_rejection_wick_ratio",
        f"{_p}_entry_time", f"{_p}_entry", f"{_p}_stop",
        f"{_p}_risk_pct", f"{_p}_risk_atr", f"{_p}_cost_r",
        f"{_p}_demand_source", f"{_p}_demand_lower", f"{_p}_demand_upper",
        f"{_p}_demand_target", f"{_p}_room_r", f"{_p}_room_pass",
        f"{_p}_tp1", f"{_p}_tp2", f"{_p}_tp1_hit", f"{_p}_tp1_time",
        f"{_p}_ft_state", f"{_p}_ft_pass", f"{_p}_ft_mfe_r",
        f"{_p}_gross_r", f"{_p}_net_r", f"{_p}_hold_bars", f"{_p}_exit_time",
    ]

CSV_FIELDS = V444_FIELDS + EVENT_FIELDS + VARIANT_FIELDS


def main():
    report = run_v446_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v446_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v446_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "m1a_fills": sum(r.get("v440_net_r") is not None for r in rows),
        "m1b_fills": sum(r.get("v441_m1_net_r") is not None for r in rows),
        "m2_v444_fills": sum(r.get("v444_m2_net_r") is not None for r in rows),
        "m2_break_events": sum(int(r.get("v446_m2_event_found") or 0) for r in rows),
        "m2_r1_fills": sum(r.get("v446_m2_r1_net_r") is not None for r in rows),
        "m2_r2_fills": sum(r.get("v446_m2_r2_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
