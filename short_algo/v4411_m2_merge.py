"""V4.4.11 M2 merge: compare ATR-stop variants and entry routes."""
import json, os, sys
from collections import Counter
from glob import glob
import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v441_main import _write_csv, _write_json
from .v4411_m2_config import (
    V4411_COOLDOWN_HOURS, V4411_MIN_PF, V4411_MIN_UNIQUE_FILLS,
    V4411_STOP_ATR_VARIANTS,
)
from .v4411_m2_main import CSV_FIELDS


def _load(root):
    out=[]
    for p in sorted(glob(os.path.join(root,"**","v4411_m2_backtest.json"),recursive=True)):
        with open(p,"r",encoding="utf-8") as f: out.append(json.load(f))
    return out

def _num(v):
    try:
        x=float(v); return x if np.isfinite(x) else None
    except (TypeError,ValueError): return None

def _pct(n,d): return round(100*n/d,2) if d else None

def _pf(vals):
    vals=[x for x in (_num(v) for v in vals) if x is not None]
    gain=sum(x for x in vals if x>0); loss=-sum(x for x in vals if x<0)
    if loss<=0: return 999.0 if gain>0 else None
    return round(gain/loss,4)

def _exact_events(rows):
    d={}
    for r in sorted(rows,key=lambda x:(str(x.get("signal_time")),str(x.get("symbol")))):
        bt=r.get("v4411_m2_break_time")
        if not bt: continue
        d.setdefault((str(r.get("symbol")),str(bt),str(r.get("v4411_m2_support_level"))),r)
    return list(d.values())

def _unique(events):
    last={}; out=[]
    for r in sorted(events,key=lambda x:(str(x.get("v4411_m2_break_time")),str(x.get("symbol")))):
        s=str(r.get("symbol")); t=pd.Timestamp(r.get("v4411_m2_break_time")); prev=last.get(s)
        if prev is not None and (t-prev)<pd.Timedelta(hours=int(V4411_COOLDOWN_HOURS)): continue
        last[s]=t; out.append(r)
    return out

def _entries(rows): return [r for r in rows if r.get("v4411_m2_entry_time") is not None]

def _metrics(entries, stop_atr):
    tag=str(stop_atr).replace(".","_"); p=f"v4411_m2_s{tag}"
    fills=[r for r in entries if _num(r.get(f"{p}_net_r")) is not None]
    net=[float(r[f"{p}_net_r"]) for r in fills]; gross=[float(r[f"{p}_gross_r"]) for r in fills]
    return {
        "fills":len(fills),
        "positive_net":sum(x>0 for x in net),
        "positive_net_pct":_pct(sum(x>0 for x in net),len(net)),
        "stop_pct":_pct(sum(r.get(f"{p}_state")=="SL_FIRST" for r in fills),len(fills)),
        "tp1_hit_pct":_pct(sum(int(r.get(f"{p}_tp1_hit") or 0) for r in fills),len(fills)),
        "tp2_hit_pct":_pct(sum(int(r.get(f"{p}_tp2_hit") or 0) for r in fills),len(fills)),
        "gross_expectancy_r":round(float(np.mean(gross)),5) if gross else None,
        "net_expectancy_r":round(float(np.mean(net)),5) if net else None,
        "profit_factor":_pf(net),
        "total_net_r":round(sum(net),5),
        "avg_cost_r":round(float(np.mean([float(r[f"{p}_cost_r"]) for r in fills])),5) if fills else None,
        "states":dict(sorted(Counter(str(r.get(f"{p}_state") or "NONE") for r in fills).items())),
    }

def _gate(m):
    checks={
        "fills_ge_min":int(m.get("fills") or 0)>=int(V4411_MIN_UNIQUE_FILLS),
        "net_expectancy_gt_0":m.get("net_expectancy_r") is not None and float(m["net_expectancy_r"])>0,
        "pf_gt_min":m.get("profit_factor") is not None and float(m["profit_factor"])>float(V4411_MIN_PF),
    }
    return {"checks":checks,"pass":all(checks.values())}

def _route(entries, reason):
    return [r for r in entries if str(r.get("v4411_m2_ready_reason") or "")==reason]

def _summary(report):
    a=report["analysis"]; lines=[
        "# Crypto Short V4.4.11 — M2 Entry + Stop Study 60d","",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- Signal and entry are frozen from V4.4.10/V4.4.9.",
        "- Only execution changes: 1.5 / 1.75 / 2.0 ATR stops, 50% at 2R, 50% at 3R, BE after TP1.",
        "","## Unique 96h — all M2 entries",
    ]
    for s in V4411_STOP_ATR_VARIANTS:
        lines.append(f"- Stop {s:g} ATR: {a['unique_all'][str(s)]}")
    lines += ["","## Unique 96h — PERSISTENT_NO_RECLAIM_LOWER_HIGHS"]
    for s in V4411_STOP_ATR_VARIANTS:
        lines.append(f"- Stop {s:g} ATR: {a['unique_persistent'][str(s)]}")
    lines += ["","## Unique 96h — REPEATED_FAILED_RECLAIM_LOWER_HIGH"]
    for s in V4411_STOP_ATR_VARIANTS:
        lines.append(f"- Stop {s:g} ATR: {a['unique_repeated'][str(s)]}")
    lines += ["",f"- Gates: {a['gates']}","- RESEARCH_ONLY. No automatic live promotion."]
    return "\n".join(lines)

def merge_reports(reports):
    if not reports: raise RuntimeError("No V4.4.11 M2 reports")
    expected=max(int(r.get("shard_count") or 1) for r in reports)
    found={int(r.get("shard_index")) for r in reports}
    if found!=set(range(expected)): raise RuntimeError(f"Incomplete V4.4.11 shards: {sorted(found)}")
    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1: raise RuntimeError("Manifest mismatch")
    first=reports[0]; frozen=set((first.get("manifest") or {}).get("symbols") or [])
    symbols=[]; raw=[]; errors=[]
    for r in reports:
        symbols.extend(r.get("selected_symbols") or []); raw.extend(r.get("trades") or []); errors.extend(r.get("errors") or [])
    us=set(symbols)
    integrity={"ok":len(reports)==expected and len(symbols)==len(us) and us==frozen,
               "expected_shards":expected,"found_shards":len(reports),"frozen_symbol_count":len(frozen),"merged_symbol_count":len(us)}
    if not integrity["ok"]: raise RuntimeError(f"Integrity failure: {integrity}")
    d={}
    for r in raw: d.setdefault((r.get("symbol"),r.get("signal_time")),r)
    rows=sorted(d.values(),key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    events=_exact_events(rows); unique_events=_unique(events); entries=_entries(events); ue=_entries(unique_events)
    persistent=_route(ue,"PERSISTENT_NO_RECLAIM_LOWER_HIGHS")
    repeated=_route(ue,"REPEATED_FAILED_RECLAIM_LOWER_HIGH")
    all_m={str(s):_metrics(ue,s) for s in V4411_STOP_ATR_VARIANTS}
    p_m={str(s):_metrics(persistent,s) for s in V4411_STOP_ATR_VARIANTS}
    r_m={str(s):_metrics(repeated,s) for s in V4411_STOP_ATR_VARIANTS}
    gates={
        "all":{str(s):_gate(all_m[str(s)]) for s in V4411_STOP_ATR_VARIANTS},
        "persistent":{str(s):_gate(p_m[str(s)]) for s in V4411_STOP_ATR_VARIANTS},
        "repeated":{str(s):_gate(r_m[str(s)]) for s in V4411_STOP_ATR_VARIANTS},
    }
    analysis={
        "counts":{"raw_rows":len(rows),"exact_break_events":len(events),"unique_96h_break_events":len(unique_events),
                  "exact_entries":len(entries),"unique_96h_entries":len(ue),"persistent_unique":len(persistent),"repeated_unique":len(repeated)},
        "unique_all":all_m,"unique_persistent":p_m,"unique_repeated":r_m,"gates":gates,
        "research_status":"RESEARCH_ONLY","entry_logic_frozen":True,"parameter_grid_searched":False,
    }
    return {"engine":"Crypto Short V4.4.11 M2 Entry Stop Study","manifest_id":next(iter(ids)),"manifest":first.get("manifest"),
            "manifest_integrity":integrity,"period_start":first.get("period_start"),"period_end":first.get("period_end"),
            "future_end":first.get("future_end"),"days":first.get("days"),"selected_symbols":sorted(us),"selected_symbol_count":len(us),
            "analysis":analysis,"trades":rows,"errors":errors}

def main():
    root=sys.argv[1] if len(sys.argv)>1 else "shard_outputs"
    report=merge_reports(_load(root)); os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v4411_m2_backtest.json"),report)
    _write_json(os.path.join(OUTPUT_DIR,"v4411_m2_analysis.json"),report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR,"v4411_m2_manifest.json"),report["manifest"])
    _write_csv(os.path.join(OUTPUT_DIR,"v4411_m2_candidates.csv"),report["trades"],fields=CSV_FIELDS)
    with open(os.path.join(OUTPUT_DIR,"v4411_m2_summary.md"),"w",encoding="utf-8") as f: f.write(_summary(report))
    print(json.dumps({"integrity":report["manifest_integrity"],"errors":len(report["errors"]),"analysis":report["analysis"]},ensure_ascii=False,indent=2))
    return 0 if not report["errors"] else 2

if __name__=="__main__": sys.exit(main())
