"""M3 V3.6 shard writer."""
import csv,json,os,sys
from .config import OUTPUT_DIR
from .m3_v36_backtest import run_m3_v36_backtest

FIELDS=[
"symbol","signal_time","m3v36_market_state",
"m3v36_coin_return_4h_pct","m3v36_coin_return_24h_pct",
"m3v36_market_return_4h_pct","m3v36_market_return_24h_pct",
"m3v36_relative_weakness_4h_pct","m3v36_relative_weakness_24h_pct",
"m3v36_distance_to_ema20_atr1h","m3v36_distance_to_ema50_atr1h",
"m3v36_breakdown_strength_atr1h","m3v36_volume_expansion_1h",
"m3v21_retest_quality_score","m3v21_retest_penetration_atr15",
"m3v36_entry_state","m3v36_entry","m3v36_entry_time","m3v36_entry_wait_bars",
"m3v36_hit_3pct_24h","m3v36_minutes_to_3pct","m3v36_pre3pct_mae_pct",
"m3v36_clean3_adverse_0_5","m3v36_clean3_adverse_0_75","m3v36_clean3_adverse_1_0",
"m3v36_max_favorable_pct_24h","m3v36_max_adverse_pct_24h"
]

def main():
    report=run_m3_v36_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v36_backtest.json"),"w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v36_rows.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore")
        w.writeheader()
        for row in report["rows"]:
            w.writerow({k:row.get(k) for k in FIELDS})
    print(json.dumps({
        "manifest_id":report["manifest_id"],
        "shard":report["shard_index"],
        "symbols":report["selected_symbol_count"],
        "rows":len(report["rows"]),
        "errors":len(report["errors"]),
    },indent=2))
    return 0 if report["selected_symbol_count"] else 2

if __name__=="__main__":
    sys.exit(main())
