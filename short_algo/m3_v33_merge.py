"""Merge M3 V3.3 shards and compare retest-entry variants."""
import json,os,sys
from collections import Counter
from glob import glob
import numpy as np
from .config import OUTPUT_DIR

def _num(x):
    try:
        y=float(x); return y if np.isfinite(y) else None
    except (TypeError,ValueError): return None

def _pct(n,d): return round(100.0*n/d,2) if d else None

def _q(vals,q=0.5):
    arr=[_num(x) for x in vals]; arr=[x for x in arr if x is not None]
    return round(float(np.quantile(arr,q)),5) if arr else None

def _metrics(rows,days,code):
    p=f"m3v33_{code}_"
    filled=[r for r in rows if r.get(p+"state")=="FILLED"]
    hits=[r for r in filled if int(r.get(p+"hit_3pct_24h") or 0)]
    return {
        "core_candidates":len(rows),
        "filled_entries":len(filled),
        "fill_rate_pct":_pct(len(filled),len(rows)),
        "entries_per_day":round(len(filled)/max(float(days),1.0),3),
        "hit_3pct_24h_pct":_pct(len(hits),len(filled)),
        "clean3_before_0_5_pct":_pct(sum(int(r.get(p+"clean3_adverse_0_5") or 0) for r in filled),len(filled)),
        "clean3_before_0_75_pct":_pct(sum(int(r.get(p+"clean3_adverse_0_75") or 0) for r in filled),len(filled)),
        "clean3_before_1_0_pct":_pct(sum(int(r.get(p+"clean3_adverse_1_0") or 0) for r in filled),len(filled)),
        "median_pre3pct_mae_pct":_q([r.get(p+"pre3pct_mae_pct") for r in filled]),
        "p75_pre3pct_mae_pct":_q([r.get(p+"pre3pct_mae_pct") for r in filled],0.75),
        "median_minutes_to_3pct_hits":_q([r.get(p+"minutes_to_3pct") for r in hits]),
        "median_entry_distance_atr15":_q([r.get(p+"distance_atr15") for r in filled]),
        "median_wait_bars":_q([r.get(p+"wait_bars") for r in filled]),
        "market_states":dict(sorted(Counter(str(r.get("m3v33_market_state") or "UNKNOWN") for r in filled).items())),
    }

def main(root="m3v33_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v33_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f: reports.append(json.load(f))
    if not reports: raise RuntimeError("No M3 V3.3 reports")
    expected=max(int(r["shard_count"]) for r in reports)
    found={int(r["shard_index"]) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete shards {sorted(found)}")
    manifest_ids={r["manifest_id"] for r in reports}
    if len(manifest_ids)!=1: raise RuntimeError("Manifest mismatch")

    rows=[]; errors=[]; symbols=[]
    for report in reports:
        rows+=report.get("rows",[]); errors+=report.get("errors",[]); symbols+=report.get("selected_symbols",[])
    dedup={}
    for row in rows: dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values()); days=int(reports[0]["days"])

    analysis={
        "core_candidates":{"count":len(rows),"per_day":round(len(rows)/max(float(days),1.0),3)},
        "entry_a_next_bar_open":_metrics(rows,days,"a"),
        "entry_b_poi_limit":_metrics(rows,days,"b"),
        "entry_c_rejection_close":_metrics(rows,days,"c"),
    }
    out={"engine":"M3 V3.3 Retest Entry Optimization","manifest_id":next(iter(manifest_ids)),"days":days,
         "symbols":len(set(symbols)),"errors":errors,"analysis":analysis,"rows":rows,
         "research_status":"SAME_PERIOD_DEVELOPMENT_NOT_INDEPENDENT_OOS",
         "note":"V3.3 freezes the V2.1 broken-support + quality + volatility cohort and changes only entry execution."}

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v33_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v33_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V3.3 — Retest Entry Optimization\n\n")
        f.write("A = next 15m open after failed retest (V2.1 baseline).\n\n")
        f.write("B = sell limit at broken-support POI for up to 2 bars.\n\n")
        f.write("C = failed-retest close if distance to POI <= 0.35 ATR15.\n\n")
        for key,value in analysis.items(): f.write(f"## {key}\n{value}\n\n")
        f.write("Same-period development only; no live-rule promotion without independent validation.\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v33_shards"))
