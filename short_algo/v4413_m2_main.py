"""V4.4.13 M2 shard writer."""
import json, os, sys
from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4413_m2_backtest import run_v4413_m2_backtest

CSV_FIELDS=[
    "manifest_id","symbol","signal_time","atr_1h","current_price","relative_4h_pct",
    "v428_trend_phase","v428_structure_score",
    "v4413_m2_state","v4413_m2_break_time","v4413_m2_support_level",
    "v4413_m2_support_lower","v4413_m2_support_upper","v4413_m2_ready_reason",
    "v4413_m2_ready_time","v4413_m2_watch_hours","v4413_m2_failed_reclaim_attempts",
    "v4413_m2_retest_attempts","v4413_m2_pivot_high_count","v4413_m2_bars_below",
    "v4413_m2_flip_anchor_high","v4413_m2_prior_flip_high","v4413_m2_lower_high_drop_atr",
    "v4413_m2_entry_selection_state","v4413_m2_entry_time","v4413_m2_entry",
    "v4413_m2_entry_below_support_atr","v4413_m2_atr_at_entry",
    "v4413_m2_exec_state","v4413_m2_exec_stop_atr","v4413_m2_exec_stop",
    "v4413_m2_exec_risk_atr","v4413_m2_exec_risk_pct","v4413_m2_exec_cost_r",
    "v4413_m2_exec_tp1_atr","v4413_m2_exec_tp2_atr","v4413_m2_exec_tp1_r",
    "v4413_m2_exec_tp2_r","v4413_m2_exec_tp1","v4413_m2_exec_tp2",
    "v4413_m2_exec_tp1_hit","v4413_m2_exec_tp1_time","v4413_m2_exec_tp2_hit",
    "v4413_m2_exec_tp2_time","v4413_m2_exec_gross_r","v4413_m2_exec_net_r",
    "v4413_m2_exec_hold_bars","v4413_m2_exec_exit_time",
]

def main():
    report=run_v4413_m2_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v4413_m2_backtest.json"),report)
    _write_csv(os.path.join(OUTPUT_DIR,"v4413_m2_candidates.csv"),report.get("trades") or [],fields=CSV_FIELDS)
    entries=[r for r in report.get("trades") or [] if r.get("v4413_m2_entry_time") is not None]
    print(json.dumps({"manifest_id":report.get("manifest_id"),"shard_index":report.get("shard_index"),
                      "symbols":report.get("selected_symbol_count"),"rows":len(report.get("trades") or []),
                      "persistent_entries":len(entries),"errors":len(report.get("errors") or [])},ensure_ascii=False,indent=2))
    return 0 if report.get("selected_symbol_count",0)>0 else 2

if __name__=="__main__": sys.exit(main())
