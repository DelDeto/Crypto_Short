"""Merge M3 V4.3 exit-architecture study."""
import json,os,sys
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
from .m3_v43_config import M3_V43_FIXED_TARGETS

VARIANTS=[f"fixed_{str(x).replace('.','_')}R" for x in M3_V43_FIXED_TARGETS]+["partial_50_at_1_5R_rest_3R"]

def _pct(n,d):return round(100.0*n/d,2) if d else None
def _mean(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.median(xs)),5) if xs else None

def _metrics(rows,name,days):
    vals=[]
    for row in rows:
        v=((row.get("m3v43_exit_variants") or {}).get(name) or {})
        if int(v.get("valid") or 0)==1:vals.append(v)
    wins=sum(1 for v in vals if v.get("state") in ("TP","TP_FINAL"))
    sls=sum(int(v.get("sl_hit") or 0) for v in vals)
    first=sum(int(v.get("first_target_hit") or 0) for v in vals)
    return {"entries":len(vals),"entries_per_day":round(len(vals)/max(float(days),1),3),"positive_exit_pct":_pct(wins,len(vals)),"sl_hit_pct":_pct(sls,len(vals)),"expectancy_r":_mean([v.get("result_r") for v in vals]),"median_result_r":_med([v.get("result_r") for v in vals]),"partial_first_hit_pct":_pct(first,len(vals)) if name.startswith("partial_") else None,"median_minutes":_med([v.get("minutes") for v in vals])}

def main(root="m3v43_shards"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v43_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.3 reports")
    expected=max(int(r["shard_count"]) for r in reps);found={int(r["shard_index"]) for r in reps}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
    mids={r["manifest_id"] for r in reps}
    if len(mids)!=1:raise RuntimeError("Manifest mismatch")
    rows=[];errors=[];symbols=[]
    for r in reps:rows+=r.get("rows",[]);errors+=r.get("errors",[]);symbols+=r.get("selected_symbols",[])
    dedup={}
    for row in rows:dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values());m=reps[0]["manifest"];bd=int(m["block_days"]);total=bd*int(m["block_count"])

    analysis={}
    for name in VARIANTS:
        blocks=[]
        for b in m["blocks"]:
            br=[x for x in rows if int(x.get("m3v43_block") or 0)==int(b["block"])]
            blocks.append({"block":int(b["block"]),"start":b["start"],"end":b["end"],**_metrics(br,name,bd)})
        analysis[name]={"aggregate":_metrics(rows,name,total),"blocks":blocks,"active_blocks":sum(1 for b in blocks if (b.get("entries") or 0)>0),"positive_expectancy_blocks":sum(1 for b in blocks if b.get("expectancy_r") is not None and b["expectancy_r"]>0),"median_block_expectancy_r":_med([b.get("expectancy_r") for b in blocks]),"min_block_expectancy_r":min([b["expectancy_r"] for b in blocks if b.get("expectancy_r") is not None],default=None)}

    out={"engine":"M3 V4.3 Exit Architecture","manifest_id":next(iter(mids)),"period_start":m["period_start"],"period_end":m["period_end"],"symbols":len(set(symbols)),"errors":errors,"analysis":analysis,"research_status":"SAME_PERIOD_EXIT_ARCHITECTURE_DEVELOPMENT_CURRENT_UNIVERSE_CAVEAT","note":"Frozen V4.2 setup/entry/structural SL. Exit targets 1.5R/2R/2.5R/3R plus 50% at1.5R + 50% at3R are exploratory on the V4.2-era window; selected exit requires later OOS validation."}
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v43_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v43_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.3 — Exit Architecture Study\n\n")
        f.write("Frozen V4.2 setup, entry and structural SL. Exit variants only. Partial = 50% at 1.5R, remaining 50% at 3R, original SL unchanged.\n\n")
        for k,v in analysis.items():f.write(f"## {k}\n{json.dumps(v,ensure_ascii=False,indent=2)}\n\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v43_shards"))
