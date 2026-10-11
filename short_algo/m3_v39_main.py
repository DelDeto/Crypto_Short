"""M3 V3.9 shard writer."""
import csv,json,os,sys
from .config import OUTPUT_DIR
from .m3_v39_backtest import run_m3_v39_backtest
from .m3_v39_config import M3_V39_ENTRY_OFFSETS_ATR15, M3_V39_STOP_CAPS_PCT


def _flatten_rows(rows):
    flat=[]
    for row in rows:
        base={
            "symbol":row.get("symbol"),
            "signal_time":row.get("signal_time"),
            "block":row.get("m3v39_block"),
            "rw24":row.get("m3v39_relative_weakness_24h_pct"),
            "volume1h":row.get("m3v39_volume_expansion_1h"),
            "poi":row.get("m3v39_poi"),
            "atr15":row.get("m3v39_atr15"),
        }
        for name in M3_V39_ENTRY_OFFSETS_ATR15:
            v=(row.get("m3v39_variants") or {}).get(name) or {}
            item={**base,
                "variant":name,
                "offset_atr15":v.get("offset_atr15"),
                "limit_price":v.get("limit_price"),
                "fill_state":v.get("fill_state"),
                "entry":v.get("entry"),
                "entry_time":v.get("entry_time"),
                "wait_bars":v.get("wait_bars"),
                "hit_3pct_24h":v.get("hit_3pct_24h"),
                "minutes_to_3pct":v.get("minutes_to_3pct"),
                "pre3pct_mae_pct":v.get("pre3pct_mae_pct"),
                "max_favorable_pct_24h":v.get("max_favorable_pct_24h"),
                "max_adverse_pct_24h":v.get("max_adverse_pct_24h"),
            }
            for cap in M3_V39_STOP_CAPS_PCT:
                label=str(float(cap)).replace(".","_")
                item[f"target_before_stop_{label}pct"]=v.get(f"target_before_stop_{label}pct")
            flat.append(item)
    return flat


def main():
    report=run_m3_v39_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v39_backtest.json"),"w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,default=str)

    flat=_flatten_rows(report["rows"])
    fields=sorted({k for row in flat for k in row.keys()}) if flat else ["symbol","signal_time","variant"]
    with open(os.path.join(OUTPUT_DIR,"m3_v39_rows.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        for row in flat:
            w.writerow(row)

    print(json.dumps({
        "manifest_id":report["manifest_id"],
        "shard":report["shard_index"],
        "symbols":report["selected_symbol_count"],
        "setups":len(report["rows"]),
        "variant_rows":len(flat),
        "errors":len(report["errors"]),
    },indent=2))
    return 0 if report["selected_symbol_count"] else 2


if __name__=="__main__":
    sys.exit(main())
