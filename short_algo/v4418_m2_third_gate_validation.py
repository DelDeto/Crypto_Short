"""V4.4.18 M2 — third-gate validation on frozen V4.4.14 360D cohort.

Compare:
D  = RISK_OFF AND S4_MACRO_BEAR
E1 = D AND ema20_distance_atr >= 1.36
E2 = D AND anti_bottom_total >= 17

Research-only. No production promotion.
"""
import json, os, sys
import numpy as np
import pandas as pd

COOLDOWN_HOURS=96
MIN_FILLS=20
MIN_PF=1.50

def _num(v):
    try:
        x=float(v); return x if np.isfinite(x) else None
    except (TypeError,ValueError): return None

def _pct(n,d): return round(100*n/d,2) if d else None

def _pf(vals):
    vals=[x for x in (_num(v) for v in vals) if x is not None]
    g=sum(x for x in vals if x>0); l=-sum(x for x in vals if x<0)
    if l<=0:return 999.0 if g>0 else None
    return round(g/l,4)

def _metrics(rows):
    vals=[float(r["v4414_m2_exec_net_r"]) for r in rows if _num(r.get("v4414_m2_exec_net_r")) is not None]
    return {
      "fills":len(vals),
      "positive":sum(x>0 for x in vals),
      "positive_pct":_pct(sum(x>0 for x in vals),len(vals)),
      "net_expectancy_r":round(float(np.mean(vals)),5) if vals else None,
      "profit_factor":_pf(vals),
      "total_net_r":round(float(sum(vals)),5),
      "tp1_hit_pct":_pct(sum(int(r.get("v4414_m2_exec_tp1_hit") or 0) for r in rows),len(rows)),
      "tp2_hit_pct":_pct(sum(int(r.get("v4414_m2_exec_tp2_hit") or 0) for r in rows),len(rows)),
    }

def _exact(rows):
    d={}
    for r in sorted(rows,key=lambda x:(str(x.get("signal_time")),str(x.get("symbol")))):
        bt=r.get("v4414_m2_break_time")
        if bt:d.setdefault((str(r.get("symbol")),str(bt),str(r.get("v4414_m2_support_level"))),r)
    return list(d.values())

def _unique(events):
    last={}; out=[]
    for r in sorted(events,key=lambda x:(str(x.get("v4414_m2_break_time")),str(x.get("symbol")))):
        s=str(r.get("symbol")); t=pd.Timestamp(r["v4414_m2_break_time"]); p=last.get(s)
        if p is not None and (t-p)<pd.Timedelta(hours=COOLDOWN_HOURS):continue
        last[s]=t; out.append(r)
    return out

def _entries(report):
    out=[]
    for r in _unique(_exact(report.get("trades") or [])):
        if r.get("v4414_m2_entry_time") is None:continue
        if _num(r.get("v4414_m2_exec_net_r")) is None:continue
        x=dict(r); x["_entry_ts"]=pd.Timestamp(r["v4414_m2_entry_time"]); out.append(x)
    return sorted(out,key=lambda r:r["_entry_ts"])

def _base_d(rows):
    return [r for r in rows if int(r.get("market_risk_off") or 0)==1 and int(r.get("s4_macro_bear") or 0)==1]

def _blocks60(rows,start,end):
    out=[]; cur=start; i=1
    while cur<end:
        nxt=min(cur+pd.Timedelta(days=60),end)
        sub=[r for r in rows if cur<=r["_entry_ts"]<nxt]
        out.append({"index":i,"start":cur.isoformat(),"end":nxt.isoformat(),**_metrics(sub)})
        i+=1; cur=nxt
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

def _bad_blocks_metrics(blocks):
    chosen=[b for b in blocks if b["index"] in (4,5)]
    fills=sum(b["fills"] for b in chosen)
    total=sum(b["total_net_r"] for b in chosen)
    return {
      "fills":fills,
      "combined_total_net_r":round(total,5),
      "both_blocks_positive":all((b["net_expectancy_r"] or 0)>0 for b in chosen if b["fills"]>0),
      "block4":chosen[0] if len(chosen)>0 else None,
      "block5":chosen[1] if len(chosen)>1 else None,
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
    if start.tzinfo is None:start=start.tz_localize("UTC")
    if end.tzinfo is None:end=end.tz_localize("UTC")

    d=_base_d(rows)
    variants={
      "D_RISK_OFF_AND_S4_MACRO_BEAR":d,
      "E1_D_PLUS_EMA_DISTANCE_GE_1_36":[r for r in d if _num(r.get("ema20_distance_atr")) is not None and float(r["ema20_distance_atr"])>=1.36],
      "E2_D_PLUS_ANTI_BOTTOM_GE_17":[r for r in d if _num(r.get("anti_bottom_total")) is not None and float(r["anti_bottom_total"])>=17],
    }

    results={}
    for name,subset in variants.items():
        blocks=_blocks60(subset,start,end)
        results[name]={
          "metrics":_metrics(subset),
          "coverage_vs_D_pct":_pct(len(subset),len(d)),
          "blocks_60d":blocks,
          "stability_60d":_stability(blocks),
          "bad_blocks_4_5":_bad_blocks_metrics(blocks),
        }

    candidate_checks={}
    for name in ("E1_D_PLUS_EMA_DISTANCE_GE_1_36","E2_D_PLUS_ANTI_BOTTOM_GE_17"):
        m=results[name]["metrics"]; b=results[name]["bad_blocks_4_5"]
        candidate_checks[name]={
          "fills_ge_min":m["fills"]>=MIN_FILLS,
          "expectancy_gt_0":m["net_expectancy_r"] is not None and m["net_expectancy_r"]>0,
          "pf_gt_1_50":m["profit_factor"] is not None and m["profit_factor"]>MIN_PF,
          "bad_blocks_combined_not_negative":b["combined_total_net_r"]>=0,
          "pass":False,
        }
        candidate_checks[name]["pass"]=all(v for k,v in candidate_checks[name].items() if k!="pass")

    analysis={
      "status":"RESEARCH_ONLY","version":"V4.4.18","days":report.get("days"),
      "unique_entries":len(rows),"base_D_fills":len(d),
      "frozen_execution":{"watch_hours":"24-48","stop_atr":1.75,"tp1_atr":2.0,"tp2_atr":3.0},
      "variants":results,"candidate_checks":candidate_checks,
      "note":"Thresholds were selected from V4.4.17 diagnostics on the same 360D sample; treat as in-sample validation, not independent OOS."
    }

    os.makedirs(outdir,exist_ok=True)
    with open(os.path.join(outdir,"v4418_m2_third_gate_validation.json"),"w",encoding="utf-8") as f:
        json.dump(analysis,f,ensure_ascii=False,indent=2)
    with open(os.path.join(outdir,"v4418_m2_third_gate_validation.md"),"w",encoding="utf-8") as f:
        f.write("# V4.4.18 M2 — Third-Gate Validation 360D\n\n")
        f.write(json.dumps(analysis,ensure_ascii=False,indent=2))
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
