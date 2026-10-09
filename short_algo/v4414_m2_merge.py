"""V4.4.14 merge: validate causal 24-48h watch-time gate."""
import json, os, sys
from glob import glob
import numpy as np
import pandas as pd
from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4414_m2_config import V4414_COOLDOWN_HOURS,V4414_MIN_PF,V4414_MIN_UNIQUE_FILLS
from .v4414_m2_main import CSV_FIELDS

def _load(root):
    out=[]
    for p in sorted(glob(os.path.join(root,"**","v4414_m2_backtest.json"),recursive=True)):
        with open(p,"r",encoding="utf-8") as f: out.append(json.load(f))
    return out
def _num(v):
    try:
        x=float(v); return x if np.isfinite(x) else None
    except (TypeError,ValueError): return None
def _pf(vals):
    vals=[x for x in (_num(v) for v in vals) if x is not None]
    g=sum(x for x in vals if x>0); l=-sum(x for x in vals if x<0)
    if l<=0:return 999.0 if g>0 else None
    return round(g/l,4)
def _pct(n,d): return round(100*n/d,2) if d else None
def _exact(rows):
    d={}
    for r in sorted(rows,key=lambda x:(str(x.get("signal_time")),str(x.get("symbol")))):
        bt=r.get("v4414_m2_break_time")
        if bt:d.setdefault((str(r.get("symbol")),str(bt),str(r.get("v4414_m2_support_level"))),r)
    return list(d.values())
def _unique(events):
    last={}; out=[]
    for r in sorted(events,key=lambda x:(str(x.get("v4414_m2_break_time")),str(x.get("symbol")))):
        s=str(r.get("symbol")); t=pd.Timestamp(r.get("v4414_m2_break_time")); p=last.get(s)
        if p is not None and (t-p)<pd.Timedelta(hours=int(V4414_COOLDOWN_HOURS)):continue
        last[s]=t; out.append(r)
    return out
def _metrics(rows):
    fills=[r for r in rows if _num(r.get("v4414_m2_exec_net_r")) is not None]
    net=[float(r["v4414_m2_exec_net_r"]) for r in fills]
    return {"fills":len(fills),"positive":sum(x>0 for x in net),"positive_pct":_pct(sum(x>0 for x in net),len(net)),
            "net_expectancy_r":round(float(np.mean(net)),5) if net else None,
            "profit_factor":_pf(net),"total_net_r":round(sum(net),5),
            "tp1_hit_pct":_pct(sum(int(r.get("v4414_m2_exec_tp1_hit") or 0) for r in fills),len(fills)),
            "tp2_hit_pct":_pct(sum(int(r.get("v4414_m2_exec_tp2_hit") or 0) for r in fills),len(fills))}
def merge_reports(reports):
    if not reports: raise RuntimeError("No V4.4.14 reports")
    expected=max(int(r.get("shard_count") or 1) for r in reports); found={int(r.get("shard_index")) for r in reports}
    if found!=set(range(expected)):raise RuntimeError(f"Incomplete shards: {sorted(found)}")
    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1:raise RuntimeError("Manifest mismatch")
    first=reports[0]; frozen=set((first.get("manifest") or {}).get("symbols") or [])
    syms=[]; raw=[]; errors=[]
    for r in reports:
        syms.extend(r.get("selected_symbols") or []); raw.extend(r.get("trades") or []); errors.extend(r.get("errors") or [])
    us=set(syms)
    integrity={"ok":len(reports)==expected and len(syms)==len(us) and us==frozen,"expected_shards":expected,"found_shards":len(reports),
               "frozen_symbol_count":len(frozen),"merged_symbol_count":len(us)}
    if not integrity["ok"]:raise RuntimeError(f"Integrity failure: {integrity}")
    d={}
    for r in raw:d.setdefault((r.get("symbol"),r.get("signal_time")),r)
    rows=sorted(d.values(),key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    events=_unique(_exact(rows))
    entries=[r for r in events if r.get("v4414_m2_entry_time") is not None]
    m=_metrics(entries)
    gate={"fills_ge_min":m["fills"]>=int(V4414_MIN_UNIQUE_FILLS),
          "net_expectancy_gt_0":m["net_expectancy_r"] is not None and m["net_expectancy_r"]>0,
          "pf_gt_min":m["profit_factor"] is not None and m["profit_factor"]>float(V4414_MIN_PF)}
    analysis={"counts":{"raw_rows":len(rows),"unique_events":len(events),"watch_gate_pass":sum(int(r.get("v4414_m2_watch_gate_pass") or 0) for r in events),
                        "unique_entries":len(entries)},"metrics":m,"gate":{"checks":gate,"pass":all(gate.values())},
              "rule":{"route":"PERSISTENT_NO_RECLAIM_LOWER_HIGHS","watch_hours":"24-48","stop_atr":1.75,"tp1_atr":2.0,"tp2_atr":3.0},
              "research_status":"RESEARCH_ONLY","causal_watch_gate":True}
    return {"engine":"Crypto Short V4.4.14 M2 Watch Gate Validation","manifest_id":next(iter(ids)),"manifest":first.get("manifest"),
            "manifest_integrity":integrity,"period_start":first.get("period_start"),"period_end":first.get("period_end"),"future_end":first.get("future_end"),
            "days":first.get("days"),"selected_symbols":sorted(us),"selected_symbol_count":len(us),"analysis":analysis,"trades":rows,"errors":errors}
def main():
    root=sys.argv[1] if len(sys.argv)>1 else "shard_outputs"; report=merge_reports(_load(root)); os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v4414_m2_backtest.json"),report); _write_json(os.path.join(OUTPUT_DIR,"v4414_m2_analysis.json"),report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR,"v4414_m2_manifest.json"),report["manifest"]); _write_csv(os.path.join(OUTPUT_DIR,"v4414_m2_candidates.csv"),report["trades"],fields=CSV_FIELDS)
    with open(os.path.join(OUTPUT_DIR,"v4414_m2_summary.md"),"w",encoding="utf-8") as f:
        f.write("# Crypto Short V4.4.14 — M2 Watch Gate Validation 60d\n\n"+json.dumps(report["analysis"],ensure_ascii=False,indent=2))
    print(json.dumps({"integrity":report["manifest_integrity"],"errors":len(report["errors"]),"analysis":report["analysis"]},ensure_ascii=False,indent=2))
    return 0 if not report["errors"] else 2
if __name__=="__main__":sys.exit(main())
