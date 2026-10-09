"""M3 V3.3 shard writer."""
import csv,json,os,sys
from .config import OUTPUT_DIR
from .m3_v33_backtest import run_m3_v33_backtest

FIELDS=["symbol","signal_time","m3v33_market_state","m3v2_poi_source","m3v2_target3_atr",
"m3v21_retest_quality_score","m3v21_retest_penetration_atr15","m3v21_retest_upper_wick_ratio",
"m3v21_retest_lower_high","m3v21_retest_volume_vs_displacement","m3v33_poi","m3v33_retest_close",
"m3v33_atr15","m3v33_a_state","m3v33_a_entry","m3v33_a_entry_time","m3v33_a_distance_atr15",
"m3v33_a_hit_3pct_24h","m3v33_a_minutes_to_3pct","m3v33_a_pre3pct_mae_pct",
"m3v33_a_clean3_adverse_0_5","m3v33_a_clean3_adverse_0_75","m3v33_a_clean3_adverse_1_0",
"m3v33_b_state","m3v33_b_entry","m3v33_b_entry_time","m3v33_b_wait_bars","m3v33_b_hit_3pct_24h",
"m3v33_b_minutes_to_3pct","m3v33_b_pre3pct_mae_pct","m3v33_b_clean3_adverse_0_5",
"m3v33_b_clean3_adverse_0_75","m3v33_b_clean3_adverse_1_0","m3v33_c_state","m3v33_c_entry",
"m3v33_c_entry_time","m3v33_c_distance_atr15","m3v33_c_hit_3pct_24h","m3v33_c_minutes_to_3pct",
"m3v33_c_pre3pct_mae_pct","m3v33_c_clean3_adverse_0_5","m3v33_c_clean3_adverse_0_75",
"m3v33_c_clean3_adverse_1_0"]

def main():
    report=run_m3_v33_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v33_backtest.json"),"w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v33_rows.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader()
        for row in report["rows"]: w.writerow({k:row.get(k) for k in FIELDS})
    print(json.dumps({"manifest_id":report["manifest_id"],"shard":report["shard_index"],"symbols":report["selected_symbol_count"],"rows":len(report["rows"]),"errors":len(report["errors"])},indent=2))
    return 0 if report["selected_symbol_count"] else 2

if __name__=="__main__":
    sys.exit(main())
