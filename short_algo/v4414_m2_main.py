"""V4.4.14 M2 shard writer."""
import json, os, sys
from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4414_m2_backtest import run_v4414_m2_backtest

CSV_FIELDS=[
"manifest_id","symbol","signal_time","relative_4h_pct","v428_trend_phase","v428_structure_score",
"v4414_m2_state","v4414_m2_break_time","v4414_m2_support_level","v4414_m2_support_lower","v4414_m2_support_upper",
"v4414_m2_ready_reason","v4414_m2_ready_time","v4414_m2_watch_hours","v4414_m2_watch_gate_pass",
"v4414_m2_failed_reclaim_attempts","v4414_m2_retest_attempts","v4414_m2_pivot_high_count","v4414_m2_bars_below",
"v4414_m2_entry_selection_state","v4414_m2_entry_time","v4414_m2_entry","v4414_m2_entry_below_support_atr","v4414_m2_atr_at_entry",
"v4414_m2_exec_state","v4414_m2_exec_cost_r","v4414_m2_exec_tp1_hit","v4414_m2_exec_tp2_hit",
"v4414_m2_exec_gross_r","v4414_m2_exec_net_r","v4414_m2_exec_exit_time"]

def main():
    report=run_v4414_m2_backtest(); os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v4414_m2_backtest.json"),report)
    _write_csv(os.path.join(OUTPUT_DIR,"v4414_m2_candidates.csv"),report.get("trades") or [],fields=CSV_FIELDS)
    print(json.dumps({"entries":sum(r.get("v4414_m2_entry_time") is not None for r in report.get("trades") or []),
                      "errors":len(report.get("errors") or [])},indent=2))
    return 0 if report.get("selected_symbol_count",0)>0 else 2
if __name__=="__main__": sys.exit(main())
