"""M3 V4.5 regime attribution. Diagnostic only; creates no trading filter."""
import json,os,sys
from glob import glob
import numpy as np

from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS
from .m3_v45_config import M3_V45_NUMERIC_BINS,M3_V45_MIN_BUCKET_ENTRIES,M3_V45_MIN_BUCKET_ACTIVE_BLOCKS

FEATURE_KEYS={
 "market_return_24h_pct":"m3v45_market_return_24h_pct",
 "market_return_4h_pct":"m3v45_market_return_4h_pct",
 "relative_weakness_24h_pct":"m3v45_relative_weakness_24h_pct",
 "relative_weakness_4h_pct":"m3v45_relative_weakness_4h_pct",
 "volume_expansion_1h":"m3v45_volume_expansion_1h",
 "breakdown_strength_atr1h":"m3v45_breakdown_strength_atr1h",
 "distance_to_ema20_atr1h":"m3v45_distance_to_ema20_atr1h",
 "distance_to_ema50_atr1h":"m3v45_distance_to_ema50_atr1h",
}

def _pct(n,d):return round(100.0*n/d,2) if d else None
def _mean(xs):
 xs=[float(x) for x in xs if x is not None]
 return round(float(np.mean(xs)),5) if xs else None
def _med(xs):
 xs=[float(x) for x in xs if x is not None]
 return round(float(np.median(xs)),5) if xs else None
def _exit(row):return row.get("m3v45_frozen_exit") or {}
def _result(row):
 v=_exit(row).get("result_r")
 return float(v) if v is not None else None
def _metrics(rows):
 vals=[r for r in rows if int(_exit(r).get("valid") or 0)==1]
 rs=[_result(r) for r in vals]
 blocks=sorted({int(r.get("m3v45_block") or 0) for r in vals if int(r.get("m3v45_block") or 0)>0})
 block_exp=[]
 for b in blocks:
  br=[_result(r) for r in vals if int(r.get("m3v45_block") or 0)==b]
  block_exp.append({"block":b,"entries":len(br),"expectancy_r":_mean(br)})
 return {
  "entries":len(vals),
  "target_hit_pct":_pct(sum(1 for r in vals if _exit(r).get("state")=="TP"),len(vals)),
  "sl_hit_pct":_pct(sum(int(_exit(r).get("sl_hit") or 0) for r in vals),len(vals)),
  "expectancy_r":_mean(rs),
  "total_r":round(sum(x for x in rs if x is not None),5),
  "active_blocks":len(blocks),
  "positive_expectancy_blocks":sum(1 for x in block_exp if x["expectancy_r"] is not None and x["expectancy_r"]>0),
  "block_expectancy":block_exp,
 }
def _bucket(v,edges):
 if v is None:return "MISSING"
 x=float(v)
 for i in range(len(edges)-1):
  lo,hi=float(edges[i]),float(edges[i+1])
  if i==0 and x<=hi:return f"<= {hi:g}"
  if i==len(edges)-2 and x>lo:return f"> {lo:g}"
  if lo<x<=hi:return f"({lo:g}, {hi:g}]"
 return "OUTSIDE"
def _categorical(rows,key):
 groups={}
 for r in rows:groups.setdefault(str(r.get(key) or "MISSING"),[]).append(r)
 return {k:_metrics(v) for k,v in sorted(groups.items())}
def _numeric(rows,name,key,edges):
 groups={}
 for r in rows:groups.setdefault(_bucket(r.get(key),edges),[]).append(r)
 return {k:_metrics(v) for k,v in groups.items()}
def _block_summary(rows,block):
 br=[r for r in rows if int(r.get("m3v45_block") or 0)==int(block)]
 out={"performance":_metrics(br),"entries":len(br),"feature_medians":{},"market_state_counts":{},"anchor_source_counts":{}}
 for name,key in FEATURE_KEYS.items():out["feature_medians"][name]=_med([r.get(key) for r in br])
 for r in br:
  s=str(r.get("m3v45_market_state") or "MISSING");out["market_state_counts"][s]=out["market_state_counts"].get(s,0)+1
  a=str(r.get("m3v45_anchor_source") or "MISSING");out["anchor_source_counts"][a]=out["anchor_source_counts"].get(a,0)+1
 return out
def _spread_candidates(attribution):
 out=[]
 for dim,buckets in attribution.items():
  eligible=[]
  for label,m in buckets.items():
   if int(m.get("entries") or 0)>=int(M3_V45_MIN_BUCKET_ENTRIES) and int(m.get("active_blocks") or 0)>=int(M3_V45_MIN_BUCKET_ACTIVE_BLOCKS) and m.get("expectancy_r") is not None:
    eligible.append((label,float(m["expectancy_r"]),int(m["entries"]),int(m["active_blocks"])))
  if len(eligible)>=2:
   hi=max(eligible,key=lambda x:x[1]);lo=min(eligible,key=lambda x:x[1])
   out.append({"dimension":dim,"high_bucket":hi[0],"high_expectancy_r":round(hi[1],5),"low_bucket":lo[0],"low_expectancy_r":round(lo[1],5),"spread_r":round(hi[1]-lo[1],5),"diagnostic_only":True})
 return sorted(out,key=lambda x:-abs(x["spread_r"]))

def main(root="m3v45_shards",preflight_path="frozen/m3_v45_preflight.json"):
 reps=[]
 for p in sorted(glob(os.path.join(root,"**","m3_v45_backtest.json"),recursive=True)):
  with open(p,encoding="utf-8") as f:reps.append(json.load(f))
 if not reps:raise RuntimeError("No M3 V4.5 reports")
 expected=max(int(r["shard_count"]) for r in reps);found={int(r["shard_index"]) for r in reps}
 if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards {sorted(found)}")
 mids={r["manifest_id"] for r in reps}
 if len(mids)!=1:raise RuntimeError("Manifest mismatch")
 preflight=None
 if os.path.exists(preflight_path):
  with open(preflight_path,encoding="utf-8") as f:preflight=json.load(f)

 rows=[];coverage=[];errors=[];symbols=[]
 for r in reps:
  rows+=r.get("rows",[]);coverage+=r.get("coverage",[]);errors+=r.get("errors",[]);symbols+=r.get("selected_symbols",[])
 dedup={}
 for r in rows:dedup.setdefault((r.get("symbol"),r.get("signal_time")),r)
 rows=list(dedup.values())
 cov={c.get("symbol"):c for c in coverage}
 eligible=sum(1 for c in cov.values() if int(c.get("eligible") or 0)==1)
 data_valid=bool((preflight is None or preflight.get("data_valid")) and eligible>=int(M3_V441_MIN_ELIGIBLE_SYMBOLS))

 attribution={}
 attribution["market_state"]=_categorical(rows,"m3v45_market_state")
 attribution["anchor_source"]=_categorical(rows,"m3v45_anchor_source")
 for name,edges in M3_V45_NUMERIC_BINS.items():
  attribution[name]=_numeric(rows,name,FEATURE_KEYS[name],edges)

 m=reps[0]["manifest"]
 block_summaries=[{"block":int(b["block"]),**_block_summary(rows,int(b["block"]))} for b in m["blocks"]]
 valid_blocks=[b for b in block_summaries if b["performance"].get("expectancy_r") is not None]
 best=max(valid_blocks,key=lambda x:x["performance"]["expectancy_r"]) if valid_blocks else None
 worst=min(valid_blocks,key=lambda x:x["performance"]["expectancy_r"]) if valid_blocks else None
 contrast=None
 if best and worst:
  deltas={}
  for name in FEATURE_KEYS:
   a=best["feature_medians"].get(name);z=worst["feature_medians"].get(name)
   deltas[name]=round(float(a)-float(z),5) if a is not None and z is not None else None
  contrast={"best_block":best["block"],"best_expectancy_r":best["performance"]["expectancy_r"],"worst_block":worst["block"],"worst_expectancy_r":worst["performance"]["expectancy_r"],"best_minus_worst_feature_medians":deltas}

 out={
  "engine":"M3 V4.5 Regime Attribution",
  "manifest_id":next(iter(mids)),
  "period_start":m["period_start"],"period_end":m["period_end"],
  "selected_symbols":len(set(symbols)),"eligible_symbols":eligible,"data_valid":data_valid,
  "preflight":preflight,"errors":errors,
  "frozen_strategy_performance":_metrics(rows),
  "block_context":block_summaries,
  "best_vs_worst_block":contrast,
  "attribution":attribution,
  "exploratory_expectancy_spreads":_spread_candidates(attribution),
  "research_status":"DIAGNOSTIC_ONLY_NO_FILTER_PROMOTION",
  "note":"V4.5 changes no setup, entry, stop, or exit rule. All bins and expectancy spreads are descriptive hypothesis generation only. Do not promote a regime filter from this same window; any proposed filter requires a separately frozen OOS test.",
 }
 os.makedirs(OUTPUT_DIR,exist_ok=True)
 with open(os.path.join(OUTPUT_DIR,"m3_v45_analysis.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
 with open(os.path.join(OUTPUT_DIR,"m3_v45_summary.md"),"w",encoding="utf-8") as f:
  f.write("# M3 V4.5 — Regime Attribution Diagnostic\n\n")
  f.write("No strategy parameters changed. Diagnostics only; any apparent regime split requires separate frozen OOS validation.\n\n")
  f.write(json.dumps(out,ensure_ascii=False,indent=2))
 print(json.dumps({"performance":out["frozen_strategy_performance"],"best_vs_worst_block":contrast,"exploratory_expectancy_spreads":out["exploratory_expectancy_spreads"]},ensure_ascii=False,indent=2))
 if not data_valid:return 2
 return 0
if __name__=="__main__":
 root=sys.argv[1] if len(sys.argv)>1 else "m3v45_shards"
 preflight=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v45_preflight.json"
 raise SystemExit(main(root,preflight))
