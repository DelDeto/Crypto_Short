"""M3 V2 shard writer."""
import csv,json,os,sys
from .config import OUTPUT_DIR
from .m3_v2_backtest import run_m3_v2_backtest

FIELDS=["symbol","signal_time","m3v2_market_state","m3v2_market_r4_pct","m3v2_market_r24_pct","m3v2_state","m3v2_4h_bear_score","m3v2_impulse_atr","m3v2_pullback_retrace","m3v2_pullback_bars","m3v2_poi_source","m3v2_poi","m3v2_failed_reclaim_1h","m3v2_bearish_rejection_1h","m3v2_lower_high_1h","m3v2_entry_time","m3v2_entry","m3v2_break_level","m3v2_displacement_time","m3v2_retest_time","m3v2_displacement_body_atr15","m3v2_chase_atr15","m3v2_atr1h_pct","m3v2_target3_atr","m3v2_demand","m3v2_room_to_demand_pct","m3v2_room_gate_pass","m3v2_vol_gate_pass","m3v2_hit_3pct_24h","m3v2_minutes_to_3pct","m3v2_pre3pct_mae_pct","m3v2_max_favorable_pct_24h","m3v2_max_adverse_pct_24h","m3v2_clean3_adverse_0_5","m3v2_clean3_adverse_0_75","m3v2_clean3_adverse_1_0","m3v2_clean3_adverse_1_5"]

def main():
    r=run_m3_v2_backtest(); os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v2_backtest.json"),"w",encoding="utf-8") as f: json.dump(r,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v2_entries.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader()
        for row in r["entries"]: w.writerow({k:row.get(k) for k in FIELDS})
    print(json.dumps({"manifest_id":r["manifest_id"],"shard":r["shard_index"],"symbols":r["selected_symbol_count"],"entries":len(r["entries"]),"errors":len(r["errors"])},indent=2))
    return 0 if r["selected_symbol_count"] else 2
if __name__=="__main__": sys.exit(main())
