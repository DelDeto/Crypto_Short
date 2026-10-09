"""V4.4.16 M2 — causal-equivalent regime gate validation on V4.4.14 360D.

Uses only signal-time-safe features already stored in the frozen V4.4.14
artifact. Since the gate does not alter the frozen entry/exit mechanics,
filtering completed V14 entries by these pre-entry fields is equivalent to
applying the admission gate before entry selection.

Variants:
A BASELINE_V14
B RISK_OFF
C S4_MACRO_BEAR
D RISK_OFF_AND_S4_MACRO_BEAR  <-- primary candidate
"""
import json, os, sys
from collections import defaultdict
import numpy as np
import pandas as pd

COOLDOWN_HOURS = 96
MIN_FILLS = 30
MIN_PF = 1.50

def _num(v):
    try:
        x=float(v)
        return x if np.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def _pf(vals):
    vals=[x for x in (_num(v) for v in vals) if x is not None]
    g=sum(x for x in vals if x>0); l=-sum(x for x in vals if x<0)
    if l<=0: return 999.0 if g>0 else None
    return round(g/l,4)

def _pct(n,d): return round(100.0*n/d,2) if d else None

def _metrics(rows):
    fills=[r for r in rows if _num(r.get("v4414_m2_exec_net_r")) is not None]
    net=[float(r["v4414_m2_exec_net_r"]) for r in fills]
    return {
        "fills":len(fills),
        "positive":sum(x>0 for x in net),
        "positive_pct":_pct(sum(x>0 for x in net),len(net)),
        "net_expectancy_r":round(float(np.mean(net)),5) if net else None,
        "profit_factor":_pf(net),
        "total_net_r":round(float(sum(net)),5),
        "tp1_hit_pct":_pct(sum(int(r.get("v4414_m2_exec_tp1_hit") or 0) for r in fills),len(fills)),
        "tp2_hit_pct":_pct(sum(int(r.get("v4414_m2_exec_tp2_hit") or 0) for r in fills),len(fills)),
    }

def _exact(rows):
    d={}
    for r in sorted(rows,key=lambda x:(str(x.get("signal_time")),str(x.get("symbol")))):
        bt=r.get("v4414_m2_break_time")
        if bt:
            d.setdefault((str(r.get("symbol")),str(bt),str(r.get("v4414_m2_support_level"))),r)
    return list(d.values())

def _unique(events):
    last={}; out=[]
    for r in sorted(events,key=lambda x:(str(x.get("v4414_m2_break_time")),str(x.get("symbol")))):
        s=str(r.get("symbol")); t=pd.Timestamp(r["v4414_m2_break_time"]); p=last.get(s)
        if p is not None and (t-p)<pd.Timedelta(hours=COOLDOWN_HOURS):
            continue
        last[s]=t; out.append(r)
    return out

def _entries(report):
    rows=[]
    for r in _unique(_exact(report.get("trades") or [])):
        if r.get("v4414_m2_entry_time") is None: continue
        if _num(r.get("v4414_m2_exec_net_r")) is None: continue
        x=dict(r); x["_entry_ts"]=pd.Timestamp(r["v4414_m2_entry_time"]); rows.append(x)
    return sorted(rows,key=lambda r:r["_entry_ts"])

def _variants(rows):
    return {
        "A_BASELINE_V14": rows,
        "B_RISK_OFF": [r for r in rows if int(r.get("market_risk_off") or 0)==1],
        "C_S4_MACRO_BEAR": [r for r in rows if int(r.get("s4_macro_bear") or 0)==1],
        "D_RISK_OFF_AND_S4_MACRO_BEAR": [
            r for r in rows
            if int(r.get("market_risk_off") or 0)==1
            and int(r.get("s4_macro_bear") or 0)==1
        ],
    }

def _blocks60(rows,start,end):
    out=[]; i=1; cur=start
    while cur<end:
        nxt=min(cur+pd.Timedelta(days=60),end)
        sub=[r for r in rows if cur<=r["_entry_ts"]<nxt]
        out.append({"index":i,"start":cur.isoformat(),"end":nxt.isoformat(),**_metrics(sub)})
        cur=nxt; i+=1
    return out

def _stability(blocks):
    valid=[b for b in blocks if b["fills"]>0]
    return {
        "periods":len(valid),
        "positive_expectancy_periods":sum((b["net_expectancy_r"] or 0)>0 for b in valid),
        "pf_gt_1_periods":sum((b["profit_factor"] or 0)>1 for b in valid),
        "worst_expectancy_r":min((b["net_expectancy_r"] for b in valid if b["net_expectancy_r"] is not None),default=None),
        "best_expectancy_r":max((b["net_expectancy_r"] for b in valid if b["net_expectancy_r"] is not None),default=None),
    }

def main():
    src=sys.argv[1] if len(sys.argv)>1 else "artifact/v4414_m2_backtest.json"
    outdir=sys.argv[2] if len(sys.argv)>2 else "output"
    with open(src,"r",encoding="utf-8") as f: report=json.load(f)

    rows=_entries(report)
    expected=((report.get("analysis") or {}).get("counts") or {}).get("unique_entries")
    if expected is not None and int(expected)!=len(rows):
        raise RuntimeError(f"unique mismatch: {len(rows)} != {expected}")

    start=pd.Timestamp(report["period_start"]); end=pd.Timestamp(report["period_end"])
    if start.tzinfo is None: start=start.tz_localize("UTC")
    if end.tzinfo is None: end=end.tz_localize("UTC")

    variants=_variants(rows)
    results={}
    for name,subset in variants.items():
        blocks=_blocks60(subset,start,end)
        results[name]={
            "metrics":_metrics(subset),
            "coverage_pct":_pct(len(subset),len(rows)),
            "blocks_60d":blocks,
            "stability_60d":_stability(blocks),
        }

    d=results["D_RISK_OFF_AND_S4_MACRO_BEAR"]["metrics"]
    checks={
        "fills_ge_30":d["fills"]>=MIN_FILLS,
        "expectancy_gt_0":d["net_expectancy_r"] is not None and d["net_expectancy_r"]>0,
        "pf_gt_1_50":d["profit_factor"] is not None and d["profit_factor"]>MIN_PF,
    }

    analysis={
        "status":"RESEARCH_ONLY",
        "version":"V4.4.16",
        "days":report.get("days"),
        "unique_entries":len(rows),
        "causal_equivalence_note":"Regime fields are signal-time-safe and only decide admission; V14 entry/exit mechanics are frozen.",
        "frozen_execution":{"watch_hours":"24-48","stop_atr":1.75,"tp1_atr":2.0,"tp2_atr":3.0},
        "variants":results,
        "primary_candidate":"D_RISK_OFF_AND_S4_MACRO_BEAR",
        "gate":{"checks":checks,"pass":all(checks.values())},
        "new_rule_promoted":False,
    }

    os.makedirs(outdir,exist_ok=True)
    with open(os.path.join(outdir,"v4416_m2_regime_validation.json"),"w",encoding="utf-8") as f:
        json.dump(analysis,f,ensure_ascii=False,indent=2)
    lines=["# V4.4.16 M2 — Regime Gate Validation 360D",""]
    for name,v in results.items():
        lines.append(f"## {name}\n{json.dumps(v['metrics'],ensure_ascii=False)}\n")
        lines.append(f"60D stability: {json.dumps(v['stability_60d'],ensure_ascii=False)}\n")
    lines.append("## Primary gate")
    lines.append(json.dumps(analysis["gate"],ensure_ascii=False,indent=2))
    lines.append("\nRESEARCH_ONLY — no production rule promoted automatically.")
    with open(os.path.join(outdir,"v4416_m2_regime_validation.md"),"w",encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
