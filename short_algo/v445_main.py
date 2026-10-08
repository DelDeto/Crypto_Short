"""V4.4.5 shard writer."""
import json
import os
import sys

from .config import OUTPUT_DIR
from .v444_main import CSV_FIELDS as V444_FIELDS
from .v441_main import _write_csv, _write_json
from .v445_backtest import run_v445_backtest

M1_VARIANT_FIELDS = []
for _p in ("v445_m1a_e1", "v445_m1a_e2", "v445_m1b_e1", "v445_m1b_e2"):
    M1_VARIANT_FIELDS += [
        f"{_p}_state", f"{_p}_context_ok", f"{_p}_variant",
        f"{_p}_base_entry", f"{_p}_confirm_time", f"{_p}_retest_time",
        f"{_p}_retest_level", f"{_p}_entry_time", f"{_p}_entry",
        f"{_p}_stop", f"{_p}_risk_pct", f"{_p}_risk_atr", f"{_p}_cost_r",
        f"{_p}_demand_target", f"{_p}_room_r", f"{_p}_room_pass",
        f"{_p}_tp1", f"{_p}_tp2", f"{_p}_tp1_hit", f"{_p}_tp1_time",
        f"{_p}_ft_state", f"{_p}_ft_pass", f"{_p}_ft_mfe_r",
        f"{_p}_gross_r", f"{_p}_net_r", f"{_p}_hold_bars", f"{_p}_exit_time",
    ]

M2_EVENT_FIELDS = [
    "v445_m2_event_found", "v445_m2_event_break_time",
    "v445_m2_event_support", "v445_m2_event_support_touches",
    "v445_m2_event_pressure_score", "v445_m2_event_break_body_atr",
    "v445_m2_event_24h_max_reclaim_atr",
    "v445_m2_event_24h_max_extension_atr",
    "v445_m2_event_24h_closes_below",
    "v445_m2_event_24h_max_consecutive_below",
    "v445_m2_event_24h_first_retest_bars",
    "v445_m2_event_24h_first_reclaim_bars",
    "v445_m2_event_24h_first_1atr_extension_bars",
    "v445_m2_event_24h_end_close_below_atr",
]

M2_VARIANT_FIELDS = []
for _p in ("v445_m2_a", "v445_m2_b", "v445_m2_c"):
    M2_VARIANT_FIELDS += [
        f"{_p}_state", f"{_p}_context_ok", f"{_p}_mode",
        f"{_p}_break_time", f"{_p}_support_level", f"{_p}_support_touches",
        f"{_p}_pressure_score", f"{_p}_acceptance_closes",
        f"{_p}_entry_below_support_atr", f"{_p}_trigger_time",
        f"{_p}_trigger_reason", f"{_p}_entry_time", f"{_p}_entry",
        f"{_p}_stop", f"{_p}_risk_pct", f"{_p}_risk_atr", f"{_p}_cost_r",
        f"{_p}_demand_source", f"{_p}_demand_lower", f"{_p}_demand_upper",
        f"{_p}_demand_target", f"{_p}_room_r", f"{_p}_room_pass",
        f"{_p}_tp1", f"{_p}_tp2", f"{_p}_tp1_hit", f"{_p}_tp1_time",
        f"{_p}_ft_state", f"{_p}_ft_pass", f"{_p}_ft_mfe_r",
        f"{_p}_gross_r", f"{_p}_net_r", f"{_p}_hold_bars", f"{_p}_exit_time",
    ]

CSV_FIELDS = V444_FIELDS + M1_VARIANT_FIELDS + M2_EVENT_FIELDS + M2_VARIANT_FIELDS


def main():
    report = run_v445_backtest()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR, "v445_backtest.json"), report)
    _write_csv(
        os.path.join(OUTPUT_DIR, "v445_raw_candidates.csv"),
        report.get("trades") or [],
        fields=CSV_FIELDS,
    )
    rows = report.get("trades") or []
    print(json.dumps({
        "manifest_id": report.get("manifest_id"),
        "shard_index": report.get("shard_index"),
        "symbols": report.get("selected_symbol_count"),
        "rows": len(rows),
        "m1a_e1_fills": sum(r.get("v445_m1a_e1_net_r") is not None for r in rows),
        "m1a_e2_fills": sum(r.get("v445_m1a_e2_net_r") is not None for r in rows),
        "m1b_e1_fills": sum(r.get("v445_m1b_e1_net_r") is not None for r in rows),
        "m1b_e2_fills": sum(r.get("v445_m1b_e2_net_r") is not None for r in rows),
        "m2_events": sum(int(r.get("v445_m2_event_found") or 0) for r in rows),
        "m2_a_fills": sum(r.get("v445_m2_a_net_r") is not None for r in rows),
        "m2_b_fills": sum(r.get("v445_m2_b_net_r") is not None for r in rows),
        "m2_c_fills": sum(r.get("v445_m2_c_net_r") is not None for r in rows),
        "errors": len(report.get("errors") or []),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("selected_symbol_count", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
