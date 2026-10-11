"""Merge M3 V4.1 structural invalidation study."""
import json,os,sys
from glob import glob
import numpy as np
from .config import OUTPUT_DIR
from .m3_v41_config import M3_V41_POLICIES,M3_V41_TARGET_R
def _pct(n,d):return round(100.0*n/d,2) if d else None
def _mean(xs):
 xs=[float(x) for x in xs if x is not None]
 return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
 xs=[float(x) for x in xs if x is not None]
 return round(float(np.median(xs)),5) if xs else None
def _metrics(rows,pname,tr,days):
 key=f"r{str(float(tr)).replace('.','_')}";vals=[];pols=[]
 for row in rows:
  if row.get("m3v41_entry_state")!="FILLED":continue
  p=((row.get("m3v41_policies") or {}).get(pname) or {});r=p.get(key) or {}
  if int(r.get("valid") or 0)!=1:continue
  vals.append(r);pols.append(p)
 return {"filled_entries":len(vals),"entries_per_day":round(len(vals)/max(float(days),1),3),"target_hit_pct":_pct(sum(int(v.get("target_hit") or 0) for v in vals),len(vals)),"sl_hit_pct":_pct(sum(int(v.get("sl_hit") or 0) for v in vals),len(vals)),"expectancy_r":_mean([v.get("result_r") for v in vals]),"median_result_r":_med([v.get("result_r") for v in vals]),"median_risk_pct":_med([p.get("risk_pct") for p in pols]),"floor_applied_pct":_pct(sum(int(p.get("floor_applied") or 0) for p in pols),len(pols)),"median_mae_r":_med([v.get("mae_r") for v in vals]),"median_mfe_r":_med([v.get("mfe_r") for v in vals]),"median_minutes":_med([v.get("minutes") for v in vals])}
def main(root="m3v41_shards"):
 reps=[]
 for p in sorted(glob(os.path.join(root,"**","m3_v41_backtest.json"),recursive=True)):
  with open(p,encoding="utf-8") as f:reps.append(json.load(f))
 if not reps:raise RuntimeError("No M3 V4.1 reports")
 expected=max(int(r["shard_count"]) for r in reps);found={int(r["shard_index"]) for r in reps}
 if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
 mids={r["manifest_id"] for r in reps}
 if len(mids)!=1:raise RuntimeError("Manifest mismatch")
 rows=[];errors=[];symbols=[]
 for r in reps:rows+=r.get("rows",[]);errors+=r.get("errors",[]);symbols+=r.get("selected_symbols",[])
 dedup={}
 for row in rows:dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
 rows=list(dedup.values());m=reps[0]["manifest"];bd=int(m["block_days"]);total=bd*int(m["block_count"])
 sources={}
 for row in rows:
  s=row.get("m3v41_anchor_source")
  if s:sources[s]=sources.get(s,0)+1
 analysis={}
 for pname,cfg in M3_V41_POLICIES.items():
  analysis[pname]={"policy":cfg,"targets":{}}
  for tr in M3_V41_TARGET_R:
   blocks=[]
   for b in m["blocks"]:
    br=[x for x in rows if int(x.get("m3v41_block") or 0)==int(b["block"])]
    blocks.append({"block":int(b["block"]),"start":b["start"],"end":b["end"],**_metrics(br,pname,tr,bd)})
   analysis[pname]["targets"][f"{int(tr)}R"]={"aggregate":_metrics(rows,pname,tr,total),"blocks":blocks,"active_blocks":sum(1 for b in blocks if (b.get("filled_entries") or 0)>0),"positive_expectancy_blocks":sum(1 for b in blocks if b.get("expectancy_r") is not None and b["expectancy_r"]>0),"median_block_expectancy_r":_med([b.get("expectancy_r") for b in blocks])}
 out={"engine":"M3 V4.1 Structural Invalidation","manifest_id":next(iter(mids)),"period_start":m["period_start"],"period_end":m["period_end"],"symbols":len(set(symbols)),"errors":errors,"anchor_source_counts":sources,"analysis":analysis,"research_status":"SAME_PERIOD_TRUE_STRUCTURAL_RISK_DEVELOPMENT_CURRENT_UNIVERSE_CAVEAT","note":"Frozen RW24<=-5 and POI+0.25ATR15. Structural anchor/floor policies are exploratory and require independent OOS validation."}
 os.makedirs(OUTPUT_DIR,exist_ok=True)
 with open(os.path.join(OUTPUT_DIR,"m3_v41_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
 with open(os.path.join(OUTPUT_DIR,"m3_v41_summary.md"),"w",encoding="utf-8") as f:
  f.write("# M3 V4.1 — Structural Invalidation\n\n")
  f.write("Frozen: RW24 <= -5%, entry POI + 0.25 ATR15. Structural anchor = max(retest high, local 15m high, 1H rejection high), then buffer + minimum distance floor.\n\n")
  f.write(f"Anchor sources: {json.dumps(sources,ensure_ascii=False)}\n\n")
  for k,v in analysis.items():f.write(f"## {k}\n{json.dumps(v,ensure_ascii=False,indent=2)}\n\n")
 print(json.dumps({"anchor_sources":sources,"analysis":analysis},ensure_ascii=False,indent=2))
 return 0
if __name__=="__main__":raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v41_shards"))
