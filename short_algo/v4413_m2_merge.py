"""V4.4.13 M2 merge: diagnose persistent-route winners vs losers."""
import json, os, sys
from glob import glob
from collections import Counter
import numpy as np
import pandas as pd
from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4413_m2_config import V4413_COOLDOWN_HOURS, V4413_MIN_COHORT_FILLS
from .v4413_m2_main import CSV_FIELDS

def _load(root):
    out=[]
    for p in sorted(glob(os.path.join(root,"**","v4413_m2_backtest.json"),recursive=True)):
        with open(p,"r",encoding="utf-8") as f: out.append(json.load(f))
    return out

def _num(v):
    try:
        x=float(v); return x if np.isfinite(x) else None
    except (TypeError,ValueError): return None

def _stats(vals):
    vals=[x for x in (_num(v) for v in vals) if x is not None]
    if not vals: return {"n":0}
    a=np.asarray(vals,float)
    return {"n":len(vals),"mean":round(float(a.mean()),5),"median":round(float(np.median(a)),5),
            "p25":round(float(np.percentile(a,25)),5),"p75":round(float(np.percentile(a,75)),5)}

def _pf(vals):
    vals=[x for x in (_num(v) for v in vals) if x is not None]
    g=sum(x for x in vals if x>0); l=-sum(x for x in vals if x<0)
    if l<=0: return 999.0 if g>0 else None
    return round(g/l,4)

def _pct(n,d): return round(100*n/d,2) if d else None

def _exact(rows):
    d={}
    for r in sorted(rows,key=lambda x:(str(x.get("signal_time")),str(x.get("symbol")))):
        bt=r.get("v4413_m2_break_time")
        if bt: d.setdefault((str(r.get("symbol")),str(bt),str(r.get("v4413_m2_support_level"))),r)
    return list(d.values())

def _unique(events):
    last={}; out=[]
    for r in sorted(events,key=lambda x:(str(x.get("v4413_m2_break_time")),str(x.get("symbol")))):
        s=str(r.get("symbol")); t=pd.Timestamp(r.get("v4413_m2_break_time")); p=last.get(s)
        if p is not None and (t-p)<pd.Timedelta(hours=int(V4413_COOLDOWN_HOURS)): continue
        last[s]=t; out.append(r)
    return out

def _exec_metrics(rows):
    fills=[r for r in rows if _num(r.get("v4413_m2_exec_net_r")) is not None]
    net=[float(r["v4413_m2_exec_net_r"]) for r in fills]
    return {"fills":len(fills),"positive":sum(x>0 for x in net),"positive_pct":_pct(sum(x>0 for x in net),len(net)),
            "net_expectancy_r":round(float(np.mean(net)),5) if net else None,"profit_factor":_pf(net),
            "total_net_r":round(sum(net),5),"states":dict(sorted(Counter(str(r.get("v4413_m2_exec_state") or "NONE") for r in fills).items()))}

def _feature_summary(rows):
    keys=["v4413_m2_watch_hours","v4413_m2_entry_below_support_atr","v4413_m2_lower_high_drop_atr",
          "v4413_m2_failed_reclaim_attempts","v4413_m2_retest_attempts","v4413_m2_pivot_high_count",
          "v4413_m2_bars_below","relative_4h_pct","v428_structure_score"]
    return {k:_stats([r.get(k) for r in rows]) for k in keys}

def _bucket_entry(r):
    x=_num(r.get("v4413_m2_entry_below_support_atr"))
    if x is None:return "UNKNOWN"
    if x<=0.5:return "LE_0_5"
    if x<=1.0:return "0_5_1_0"
    if x<=1.5:return "1_0_1_5"
    return "GT_1_5"

def _bucket_watch(r):
    x=_num(r.get("v4413_m2_watch_hours"))
    if x is None:return "UNKNOWN"
    if x<=24:return "LE_24H"
    if x<=48:return "24_48H"
    if x<=72:return "48_72H"
    return "GT_72H"

def _bucket_lh(r):
    x=_num(r.get("v4413_m2_lower_high_drop_atr"))
    if x is None:return "UNKNOWN"
    if x<=0.5:return "LE_0_5"
    if x<=1.0:return "0_5_1_0"
    return "GT_1_0"

def _group(rows, fn):
    g={}
    for r in rows:g.setdefault(fn(r),[]).append(r)
    return {k:_exec_metrics(v) for k,v in sorted(g.items()) if len(v)>=int(V4413_MIN_COHORT_FILLS)}

def _summary(report):
    a=report["analysis"]
    return "\n".join([
        "# Crypto Short V4.4.13 — M2 Persistent Cohort Diagnostic 60d","",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Persistent unique entries: {a['counts']['unique_entries']}",
        f"- Frozen execution: {a['baseline']}",
        "","## Winner vs loser pre-entry features",
        f"- Winners: {a['winner_features']}",
        f"- Losers: {a['loser_features']}",
        "","## Entry-distance buckets",f"{a['entry_distance_buckets']}",
        "","## Watch-time buckets",f"{a['watch_time_buckets']}",
        "","## Lower-high-drop buckets",f"{a['lower_high_drop_buckets']}",
        "","## Trend phase",f"{a['trend_phase']}",
        "","- RESEARCH_ONLY. No new filter is promoted in V4.4.13."
    ])

def merge_reports(reports):
    if not reports: raise RuntimeError("No V4.4.13 reports")
    expected=max(int(r.get("shard_count") or 1) for r in reports); found={int(r.get("shard_index")) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete shards: {sorted(found)}")
    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1: raise RuntimeError("Manifest mismatch")
    first=reports[0]; frozen=set((first.get("manifest") or {}).get("symbols") or [])
    syms=[]; raw=[]; errors=[]
    for r in reports:
        syms.extend(r.get("selected_symbols") or []); raw.extend(r.get("trades") or []); errors.extend(r.get("errors") or [])
    us=set(syms)
    integrity={"ok":len(reports)==expected and len(syms)==len(us) and us==frozen,"expected_shards":expected,"found_shards":len(reports),
               "frozen_symbol_count":len(frozen),"merged_symbol_count":len(us)}
    if not integrity["ok"]: raise RuntimeError(f"Integrity failure: {integrity}")
    d={}
    for r in raw:d.setdefault((r.get("symbol"),r.get("signal_time")),r)
    rows=sorted(d.values(),key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    entries=[r for r in _unique(_exact(rows)) if r.get("v4413_m2_entry_time") is not None]
    winners=[r for r in entries if (_num(r.get("v4413_m2_exec_net_r")) or 0)>0]
    losers=[r for r in entries if _num(r.get("v4413_m2_exec_net_r")) is not None and float(r.get("v4413_m2_exec_net_r"))<=0]
    trend={}
    for r in entries: trend.setdefault(str(r.get("v428_trend_phase") or "UNKNOWN"),[]).append(r)
    analysis={"counts":{"raw_rows":len(rows),"unique_entries":len(entries),"winners":len(winners),"losers":len(losers)},
              "baseline":_exec_metrics(entries),"winner_features":_feature_summary(winners),"loser_features":_feature_summary(losers),
              "entry_distance_buckets":_group(entries,_bucket_entry),"watch_time_buckets":_group(entries,_bucket_watch),
              "lower_high_drop_buckets":_group(entries,_bucket_lh),
              "trend_phase":{k:_exec_metrics(v) for k,v in sorted(trend.items()) if len(v)>=int(V4413_MIN_COHORT_FILLS)},
              "research_status":"RESEARCH_ONLY","execution_frozen":True,"new_filter_promoted":False}
    return {"engine":"Crypto Short V4.4.13 M2 Persistent Cohort Diagnostic","manifest_id":next(iter(ids)),"manifest":first.get("manifest"),
            "manifest_integrity":integrity,"period_start":first.get("period_start"),"period_end":first.get("period_end"),"future_end":first.get("future_end"),
            "days":first.get("days"),"selected_symbols":sorted(us),"selected_symbol_count":len(us),"analysis":analysis,"trades":rows,"errors":errors}

def main():
    root=sys.argv[1] if len(sys.argv)>1 else "shard_outputs"; report=merge_reports(_load(root)); os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v4413_m2_backtest.json"),report); _write_json(os.path.join(OUTPUT_DIR,"v4413_m2_analysis.json"),report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR,"v4413_m2_manifest.json"),report["manifest"])
    _write_csv(os.path.join(OUTPUT_DIR,"v4413_m2_candidates.csv"),report["trades"],fields=CSV_FIELDS)
    with open(os.path.join(OUTPUT_DIR,"v4413_m2_summary.md"),"w",encoding="utf-8") as f:f.write(_summary(report))
    print(json.dumps({"integrity":report["manifest_integrity"],"errors":len(report["errors"]),"analysis":report["analysis"]},ensure_ascii=False,indent=2))
    return 0 if not report["errors"] else 2
if __name__=="__main__": sys.exit(main())
