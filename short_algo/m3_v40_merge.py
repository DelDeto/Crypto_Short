"""Merge M3 V4.0 structural-stop study."""
import json,os,sys
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
from .m3_v40_config import M3_V40_STOP_BUFFERS_ATR15, M3_V40_TARGET_R


def _pct(n,d): return round(100.0*n/d,2) if d else None

def _mean(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.mean(xs)),5) if xs else None

def _median(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.median(xs)),5) if xs else None

def _metrics(rows,stop_name,target_r,days):
    key=f"r{str(float(target_r)).replace('.','_')}"
    vals=[]
    risks=[]
    for row in rows:
        if row.get("m3v40_entry_state")!="FILLED": continue
        stop=((row.get("m3v40_stops") or {}).get(stop_name) or {})
        if int(stop.get("valid") or 0)!=1: continue
        r=stop.get(key) or {}
        if int(r.get("valid") or 0)!=1: continue
        vals.append(r); risks.append(r.get("risk_pct"))
    wins=sum(int(v.get("target_hit") or 0) for v in vals)
    stops=sum(int(v.get("stop_hit") or 0) for v in vals)
    return {
        "filled_entries":len(vals),
        "entries_per_day":round(len(vals)/max(float(days),1.0),3),
        "target_hit_pct":_pct(wins,len(vals)),
        "stop_hit_pct":_pct(stops,len(vals)),
        "expectancy_r":_mean([v.get("result_r") for v in vals]),
        "median_result_r":_median([v.get("result_r") for v in vals]),
        "median_stop_distance_pct":_median(risks),
        "median_max_adverse_r":_median([v.get("max_adverse_r") for v in vals]),
        "median_max_favorable_r":_median([v.get("max_favorable_r") for v in vals]),
        "median_minutes_to_resolution":_median([v.get("minutes_to_resolution") for v in vals]),
    }

def main(root="m3v40_shards"):
    reports=[]
    for path in sorted(glob(os.path.join(root,"**","m3_v40_backtest.json"),recursive=True)):
        with open(path,encoding="utf-8") as f: reports.append(json.load(f))
    if not reports: raise RuntimeError("No M3 V4.0 reports")
    expected=max(int(r["shard_count"]) for r in reports)
    found={int(r["shard_index"]) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete shards {sorted(found)}")
    mids={r["manifest_id"] for r in reports}
    if len(mids)!=1: raise RuntimeError("Manifest mismatch")

    rows=[]; errors=[]; symbols=[]
    for r in reports:
        rows+=r.get("rows",[]); errors+=r.get("errors",[]); symbols+=r.get("selected_symbols",[])
    dedup={}
    for row in rows: dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values())
    manifest=reports[0]["manifest"]; bd=int(manifest["block_days"]); total=bd*int(manifest["block_count"])

    analysis={}
    for stop_name,buffer_atr in M3_V40_STOP_BUFFERS_ATR15.items():
        analysis[stop_name]={"buffer_atr15":float(buffer_atr),"targets":{}}
        for target_r in M3_V40_TARGET_R:
            blocks=[]
            for block in manifest["blocks"]:
                br=[x for x in rows if int(x.get("m3v40_block") or 0)==int(block["block"])]
                blocks.append({"block":int(block["block"]),"start":block["start"],"end":block["end"],**_metrics(br,stop_name,target_r,bd)})
            analysis[stop_name]["targets"][f"{int(target_r)}R"]={
                "aggregate":_metrics(rows,stop_name,target_r,total),
                "blocks":blocks,
                "active_blocks":sum(1 for b in blocks if (b.get("filled_entries") or 0)>0),
                "positive_expectancy_blocks":sum(1 for b in blocks if b.get("expectancy_r") is not None and b["expectancy_r"]>0),
                "median_block_expectancy_r":_median([b.get("expectancy_r") for b in blocks]),
            }

    out={"engine":"M3 V4.0 Structural Stop R-Multiple","manifest_id":next(iter(mids)),
         "period_start":manifest["period_start"],"period_end":manifest["period_end"],"symbols":len(set(symbols)),
         "errors":errors,"analysis":analysis,
         "research_status":"SAME_PERIOD_STRUCTURAL_STOP_DEVELOPMENT_CURRENT_UNIVERSE_CAVEAT",
         "note":"RW24<=-5 and entry POI+0.25ATR15 were selected before this run. Structural stop buffers are exploratory on the V3.9-era window; require later independent validation."}
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v40_analysis.json"),"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v40_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.0 — Structural Stop + R-Multiple\n\n")
        f.write("Frozen setup: RW24 <= -5%; frozen entry: POI + 0.25 ATR15.\n\n")
        f.write("Stop buffers are exploratory on this development window; no live promotion.\n\n")
        for k,v in analysis.items(): f.write(f"## {k}\n{json.dumps(v,ensure_ascii=False,indent=2)}\n\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v40_shards"))
