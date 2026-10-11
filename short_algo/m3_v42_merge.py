"""Merge M3 V4.2 frozen structural-policy OOS."""
import json,os,sys,math
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
from .m3_v42_config import M3_V42_POLICY_NAME,M3_V42_TARGET_R

def _pct(n,d):return round(100.0*n/d,2) if d else None
def _mean(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.median(xs)),5) if xs else None
def _wilson(w,n,z=1.96):
    if not n:return [None,None]
    p=w/n
    den=1+z*z/n
    ctr=(p+z*z/(2*n))/den
    half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return [round(100*(ctr-half),2),round(100*(ctr+half),2)]

def _metrics(rows,days):
    vals=[];pols=[]
    key=f"r{str(float(M3_V42_TARGET_R)).replace('.','_')}"
    for row in rows:
        if row.get("m3v42_entry_state")!="FILLED":continue
        p=row.get("m3v42_frozen_policy") or {}
        r=p.get(key) or {}
        if int(r.get("valid") or 0)!=1:continue
        vals.append(r);pols.append(p)
    wins=sum(int(v.get("target_hit") or 0) for v in vals)
    sls=sum(int(v.get("sl_hit") or 0) for v in vals)
    return {
        "filled_entries":len(vals),
        "entries_per_day":round(len(vals)/max(float(days),1),3),
        "target_hit_pct":_pct(wins,len(vals)),
        "target_hit_wilson95_pct":_wilson(wins,len(vals)),
        "sl_hit_pct":_pct(sls,len(vals)),
        "expectancy_r":_mean([v.get("result_r") for v in vals]),
        "median_result_r":_med([v.get("result_r") for v in vals]),
        "median_risk_pct":_med([p.get("risk_pct") for p in pols]),
        "floor_applied_pct":_pct(sum(int(p.get("floor_applied") or 0) for p in pols),len(pols)),
        "median_mae_r":_med([v.get("mae_r") for v in vals]),
        "median_mfe_r":_med([v.get("mfe_r") for v in vals]),
        "median_minutes":_med([v.get("minutes") for v in vals]),
    }

def main(root="m3v42_shards"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v42_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.2 reports")
    expected=max(int(r["shard_count"]) for r in reps)
    found={int(r["shard_index"]) for r in reps}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
    mids={r["manifest_id"] for r in reps}
    if len(mids)!=1:raise RuntimeError("Manifest mismatch")

    rows=[];errors=[];symbols=[]
    for r in reps:
        rows+=r.get("rows",[]);errors+=r.get("errors",[]);symbols+=r.get("selected_symbols",[])
    dedup={}
    for row in rows:dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values())

    m=reps[0]["manifest"];bd=int(m["block_days"]);total=bd*int(m["block_count"])
    blocks=[]
    for b in m["blocks"]:
        br=[x for x in rows if int(x.get("m3v42_block") or 0)==int(b["block"])]
        blocks.append({"block":int(b["block"]),"start":b["start"],"end":b["end"],**_metrics(br,bd)})

    aggregate=_metrics(rows,total)
    out={
        "engine":"M3 V4.2 Frozen Structural OOS",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],
        "symbols":len(set(symbols)),"errors":errors,
        "frozen_policy_name":M3_V42_POLICY_NAME,
        "target_r":M3_V42_TARGET_R,
        "aggregate":aggregate,
        "blocks":blocks,
        "active_blocks":sum(1 for b in blocks if (b.get("filled_entries") or 0)>0),
        "positive_expectancy_blocks":sum(1 for b in blocks if b.get("expectancy_r") is not None and b["expectancy_r"]>0),
        "median_block_expectancy_r":_med([b.get("expectancy_r") for b in blocks]),
        "min_block_expectancy_r":min([b["expectancy_r"] for b in blocks if b.get("expectancy_r") is not None],default=None),
        "research_status":"STRUCTURAL_POLICY_OOS_BASE_SETUP_PREEXPOSED_CURRENT_UNIVERSE_CAVEAT",
        "note":"Frozen V4.1 structural policy tested without tuning on the V3.8-era window. This is OOS for the stop policy, but not a fully untouched end-to-end OOS because the base setup/entry was previously studied on this era. Current-universe selection remains a survivorship caveat.",
    }

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v42_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v42_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.2 — Frozen Structural OOS\n\n")
        f.write("Frozen: RW24 <= -5%, entry POI +0.25 ATR15, structural anchor from V4.1, buffer 0.50 ATR15, floor 1.25 ATR15 / 1.0%, target 3R.\n\n")
        f.write("No threshold tuning in this run. Structural-policy OOS only; base setup/entry were previously exposed to this era.\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v42_shards"))
