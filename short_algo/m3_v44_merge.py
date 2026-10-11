"""Merge M3 V4.4 frozen-exit OOS."""
import json,os,sys,math,random
from glob import glob
import numpy as np
from .config import OUTPUT_DIR

def _pct(n,d):return round(100.0*n/d,2) if d else None
def _mean(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(float(np.median(xs)),5) if xs else None
def _wilson(w,n,z=1.96):
    if not n:return [None,None]
    p=w/n;den=1+z*z/n;ctr=(p+z*z/(2*n))/den;half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return [round(100*(ctr-half),2),round(100*(ctr+half),2)]
def _bootstrap_mean_ci(vals,reps=5000):
    vals=[float(x) for x in vals if x is not None]
    if not vals:return [None,None]
    rng=random.Random(440)
    means=[]
    n=len(vals)
    for _ in range(reps):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n))/n)
    means.sort()
    return [round(means[int(0.025*(reps-1))],5),round(means[int(0.975*(reps-1))],5)]
def _max_drawdown(vals):
    curve=0.0;peak=0.0;mdd=0.0
    for x in vals:
        curve+=float(x);peak=max(peak,curve);mdd=max(mdd,peak-curve)
    return round(mdd,5)
def _metrics(rows,days):
    ordered=sorted(rows,key=lambda r:r.get("signal_time") or "")
    vals=[]
    for row in ordered:
        v=row.get("m3v44_frozen_exit") or {}
        if int(v.get("valid") or 0)==1:vals.append(v)
    rs=[v.get("result_r") for v in vals]
    wins=sum(1 for v in vals if v.get("state")=="TP")
    sls=sum(int(v.get("sl_hit") or 0) for v in vals)
    return {
        "entries":len(vals),
        "entries_per_day":round(len(vals)/max(float(days),1),3),
        "target_hit_pct":_pct(wins,len(vals)),
        "target_hit_wilson95_pct":_wilson(wins,len(vals)),
        "sl_hit_pct":_pct(sls,len(vals)),
        "expectancy_r":_mean(rs),
        "expectancy_bootstrap95_r":_bootstrap_mean_ci(rs),
        "total_r":round(sum(float(x) for x in rs if x is not None),5),
        "median_result_r":_med(rs),
        "max_drawdown_r_signal_order":_max_drawdown([x for x in rs if x is not None]),
        "median_minutes":_med([v.get("minutes") for v in vals]),
    }

def main(root="m3v44_shards"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v44_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.4 reports")
    expected=max(int(r["shard_count"]) for r in reps);found={int(r["shard_index"]) for r in reps}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
    mids={r["manifest_id"] for r in reps}
    if len(mids)!=1:raise RuntimeError("Manifest mismatch")
    rows=[];errors=[];symbols=[]
    for r in reps:rows+=r.get("rows",[]);errors+=r.get("errors",[]);symbols+=r.get("selected_symbols",[])
    dedup={}
    for row in rows:dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=list(dedup.values());m=reps[0]["manifest"];bd=int(m["block_days"]);total=bd*int(m["block_count"])
    blocks=[]
    for b in m["blocks"]:
        br=[x for x in rows if int(x.get("m3v44_block") or 0)==int(b["block"])]
        blocks.append({"block":int(b["block"]),"start":b["start"],"end":b["end"],**_metrics(br,bd)})
    aggregate=_metrics(rows,total)
    out={
        "engine":"M3 V4.4 Frozen Exit OOS",
        "manifest_id":next(iter(mids)),
        "period_start":m["period_start"],"period_end":m["period_end"],
        "symbols":len(set(symbols)),"errors":errors,
        "frozen_exit":"fixed_1_5R",
        "aggregate":aggregate,
        "blocks":blocks,
        "active_blocks":sum(1 for b in blocks if (b.get("entries") or 0)>0),
        "positive_expectancy_blocks":sum(1 for b in blocks if b.get("expectancy_r") is not None and b["expectancy_r"]>0),
        "median_block_expectancy_r":_med([b.get("expectancy_r") for b in blocks]),
        "min_block_expectancy_r":min([b["expectancy_r"] for b in blocks if b.get("expectancy_r") is not None],default=None),
        "research_status":"FROZEN_EXIT_OOS_FIXED_DATES_CURRENT_UNIVERSE_CAVEAT",
        "note":"Fixed 2025-04-07 to 2025-08-05 UTC. Frozen V4.2 setup/entry/structural SL and V4.3 fixed 1.5R exit. No exit retuning. Current-universe ranking remains a survivorship/selection caveat.",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v44_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v44_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.4 — Frozen 1.5R Exit OOS\n\n")
        f.write("Fixed dates: 2025-04-07 00:00 UTC to 2025-08-05 00:00 UTC. Frozen V4.2 setup/entry/SL + fixed 1.5R exit. No threshold tuning.\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v44_shards"))
