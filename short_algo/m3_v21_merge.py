"""Merge M3 V2.1 shards and compare refined entry cohorts."""
import json,os,sys
from collections import Counter
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
def _num(x):
    try:
        y=float(x);return y if np.isfinite(y) else None
    except (TypeError,ValueError):return None
def _pct(n,d):return round(100*n/d,2) if d else None
def _q(vals,q=.5):
    a=[_num(x) for x in vals];a=[x for x in a if x is not None]
    return round(float(np.quantile(a,q)),5) if a else None
def _metrics(rows,days):
    n=len(rows)
    return {"entries":n,"entries_per_day":round(n/max(float(days),1),3),"hit_3pct_24h_pct":_pct(sum(int(r.get("m3v2_hit_3pct_24h") or 0) for r in rows),n),"clean3_before_0_5_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_0_5") or 0) for r in rows),n),"clean3_before_0_75_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_0_75") or 0) for r in rows),n),"clean3_before_1_0_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_1_0") or 0) for r in rows),n),"median_pre3pct_mae_pct":_q([r.get("m3v2_pre3pct_mae_pct") for r in rows]),"p75_pre3pct_mae_pct":_q([r.get("m3v2_pre3pct_mae_pct") for r in rows],.75),"median_minutes_to_3pct_hits":_q([r.get("m3v2_minutes_to_3pct") for r in rows if int(r.get("m3v2_hit_3pct_24h") or 0)]),"median_quality_score":_q([r.get("m3v21_retest_quality_score") for r in rows]),"median_structural_room_pct":_q([r.get("m3v21_structural_demand_room_pct") for r in rows]),"median_retest_penetration_atr15":_q([r.get("m3v21_retest_penetration_atr15") for r in rows]),"poi_sources":dict(sorted(Counter(str(r.get("m3v2_poi_source") or "NONE") for r in rows).items()))}
def main(root="m3v21_shards"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v21_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V2.1 reports")
    expected=max(int(r["shard_count"]) for r in reps);found={int(r["shard_index"]) for r in reps}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
    ids={r["manifest_id"] for r in reps}
    if len(ids)!=1:raise RuntimeError("Manifest mismatch")
    rows=[];errors=[];syms=[]
    for r in reps:rows+=r.get("entries",[]);errors+=r.get("errors",[]);syms+=r.get("selected_symbols",[])
    dedup={}
    for r in rows:dedup.setdefault((r.get("symbol"),r.get("m3v2_entry_time")),r)
    rows=list(dedup.values());days=int(reps[0]["days"])
    q=lambda r:int(r.get("m3v21_quality_gate_pass") or 0)
    room=lambda r:int(r.get("m3v21_room_gate_pass") or 0)
    vol=lambda r:int(r.get("m3v21_vol_gate_pass") or 0)
    bs=lambda r:r.get("m3v2_poi_source")=="BROKEN_SUPPORT_1H"
    cohorts={"v21_base":rows,"quality_only":[r for r in rows if q(r)],"quality_and_vol":[r for r in rows if q(r) and vol(r)],"quality_room_vol":[r for r in rows if q(r) and room(r) and vol(r)],"broken_support_quality":[r for r in rows if bs(r) and q(r)],"broken_support_quality_vol":[r for r in rows if bs(r) and q(r) and vol(r)],"broken_support_quality_room_vol":[r for r in rows if bs(r) and q(r) and room(r) and vol(r)]}
    analysis={k:_metrics(v,days) for k,v in cohorts.items()}
    # Quality score ladder is diagnostic, not promotion.
    analysis["quality_score_ladder"]={str(s):_metrics([r for r in rows if int(r.get("m3v21_retest_quality_score") or 0)>=s],days) for s in range(2,7)}
    out={"engine":"M3 V2.1 Entry Refinement","manifest_id":next(iter(ids)),"days":days,"symbols":len(set(syms)),"errors":errors,"analysis":analysis,"entries":rows,"research_status":"RESEARCH_ONLY_SAME_PERIOD_DEVELOPMENT"}
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v21_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v21_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V2.1 — Entry Refinement\n\nGoal: improve Clean 3% entry quality, not just final 3% hit rate.\n\n")
        for k,v in analysis.items():f.write(f"## {k}\n{v}\n\n")
        f.write("Same-period development study; no rule promotion before independent validation.\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v21_shards"))
