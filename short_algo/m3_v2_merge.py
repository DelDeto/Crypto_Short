"""Merge M3 V2 shards and compare Clean-3% cohorts."""
import json,os,sys
from collections import Counter
from glob import glob
import numpy as np
from .config import OUTPUT_DIR


def _num(x):
    try:
        y=float(x); return y if np.isfinite(y) else None
    except (TypeError,ValueError): return None

def _pct(n,d): return round(100*n/d,2) if d else None

def _q(vals,q=.5):
    a=[_num(x) for x in vals]; a=[x for x in a if x is not None]
    return round(float(np.quantile(a,q)),5) if a else None

def _metrics(rows,days):
    n=len(rows); hits=sum(int(r.get("m3v2_hit_3pct_24h") or 0) for r in rows)
    return {
        "entries":n,"entries_per_day":round(n/max(float(days),1),3),
        "hit_3pct_24h_pct":_pct(hits,n),
        "clean3_mae_lt_0_5_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_0_5") or 0) for r in rows),n),
        "clean3_mae_lt_0_75_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_0_75") or 0) for r in rows),n),
        "clean3_mae_lt_1_0_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_1_0") or 0) for r in rows),n),
        "clean3_mae_lt_1_5_pct":_pct(sum(int(r.get("m3v2_clean3_adverse_1_5") or 0) for r in rows),n),
        "median_pre3pct_mae_pct":_q([r.get("m3v2_pre3pct_mae_pct") for r in rows]),
        "p75_pre3pct_mae_pct":_q([r.get("m3v2_pre3pct_mae_pct") for r in rows],.75),
        "median_minutes_to_3pct_hits":_q([r.get("m3v2_minutes_to_3pct") for r in rows if int(r.get("m3v2_hit_3pct_24h") or 0)]),
        "median_target3_atr":_q([r.get("m3v2_target3_atr") for r in rows]),
        "median_room_to_demand_pct":_q([r.get("m3v2_room_to_demand_pct") for r in rows]),
        "poi_sources":dict(sorted(Counter(str(r.get("m3v2_poi_source") or "NONE") for r in rows).items())),
        "market_states":dict(sorted(Counter(str(r.get("m3v2_market_state") or "NONE") for r in rows).items())),
    }

def main(root="m3v2_shards"):
    reports=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v2_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f: reports.append(json.load(f))
    if not reports: raise RuntimeError("No M3 V2 reports")
    expected=max(int(r["shard_count"]) for r in reports)
    found={int(r["shard_index"]) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete shards {sorted(found)}")
    ids={r["manifest_id"] for r in reports}
    if len(ids)!=1: raise RuntimeError("Manifest mismatch")
    rows=[]; errors=[]; syms=[]
    for r in reports: rows+=r.get("entries",[]); errors+=r.get("errors",[]); syms+=r.get("selected_symbols",[])
    dedup={}
    for r in rows: dedup.setdefault((r.get("symbol"),r.get("m3v2_entry_time")),r)
    rows=list(dedup.values())
    days=int(reports[0]["days"])
    cohorts={
      "retest_base":rows,
      "room_ge_3_5": [r for r in rows if int(r.get("m3v2_room_gate_pass") or 0)],
      "vol_target_le_3atr": [r for r in rows if int(r.get("m3v2_vol_gate_pass") or 0)],
      "room_and_vol": [r for r in rows if int(r.get("m3v2_room_gate_pass") or 0) and int(r.get("m3v2_vol_gate_pass") or 0)],
      "broken_support_only": [r for r in rows if r.get("m3v2_poi_source")=="BROKEN_SUPPORT_1H"],
      "broken_support_room_vol": [r for r in rows if r.get("m3v2_poi_source")=="BROKEN_SUPPORT_1H" and int(r.get("m3v2_room_gate_pass") or 0) and int(r.get("m3v2_vol_gate_pass") or 0)],
    }
    analysis={k:_metrics(v,days) for k,v in cohorts.items()}
    out={"engine":"M3 V2 Clean 3% Entry Research","manifest_id":next(iter(ids)),"days":days,"symbols":len(set(syms)),"errors":errors,"analysis":analysis,"entries":rows,"research_status":"RESEARCH_ONLY_SAME_PERIOD_DEVELOPMENT"}
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v2_analysis.json"),"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    with open(os.path.join(OUTPUT_DIR,"m3_v2_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V2 — Clean 3% Entry Research\n\n")
        f.write("Target: price falls >=3% from benchmark entry within 24h, with low adverse excursion before target.\n\n")
        for k,v in analysis.items(): f.write(f"## {k}\n{v}\n\n")
        f.write("Same-period development study; freeze rules before independent validation.\n")
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0
if __name__=="__main__": raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "m3v2_shards"))
