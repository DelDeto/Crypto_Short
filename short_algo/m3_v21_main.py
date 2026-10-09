"""M3 V2.1 shard writer."""
import csv,json,os,sys
from .config import OUTPUT_DIR
from .m3_v21_backtest import run_m3_v21_backtest
FIELDS=["symbol","signal_time","m3v21_market_state","m3v2_poi_source","m3v2_entry_time","m3v2_entry","m3v2_hit_3pct_24h","m3v2_minutes_to_3pct","m3v2_pre3pct_mae_pct","m3v2_clean3_adverse_0_5","m3v2_clean3_adverse_0_75","m3v2_clean3_adverse_1_0","m3v2_target3_atr","m3v21_retest_quality_score","m3v21_retest_penetration_atr15","m3v21_retest_close_below_break_atr15","m3v21_retest_upper_wick_ratio","m3v21_retest_lower_high","m3v21_retest_volume_vs_displacement","m3v21_structural_demand","m3v21_structural_demand_room_pct","m3v21_demand_bounce_atr","m3v21_demand_touches","m3v21_quality_gate_pass","m3v21_room_gate_pass","m3v21_vol_gate_pass"]
def main():
    r=run_m3_v21_backtest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v21_backtest.json"),"w",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v21_entries.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore");w.writeheader()
        for row in r["entries"]:w.writerow({k:row.get(k) for k in FIELDS})
    print(json.dumps({"manifest_id":r["manifest_id"],"shard":r["shard_index"],"symbols":r["selected_symbol_count"],"entries":len(r["entries"]),"errors":len(r["errors"])},indent=2));return 0 if r["selected_symbol_count"] else 2
if __name__=="__main__":sys.exit(main())
