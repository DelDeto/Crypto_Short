"""V4.4.17 M2 — Failure-regime diagnostic for V4.4.16 primary candidate.

Primary cohort:
  RISK_OFF == 1 AND S4_MACRO_BEAR == 1
Good regime training contrast:
  first three fixed 60D blocks of V14 360D
Bad regime training contrast:
  blocks 4-5 (Mar-Jul 2026)
Block 6 is held aside from regime contrast because it has only one D trade.

Research-only. No rule promoted.
"""
import json, os, sys
from collections import defaultdict
import numpy as np
import pandas as pd

COOLDOWN_HOURS=96

FEATURES=[
 "market_r4_pct","market_r24_pct","relative_4h_pct","relative_24h_pct",
 "atr_pct_1h","volume_ratio_1h","candidate_context_points",
 "ema20_distance_atr","range_position_24h","range_position_48h",
 "anti_bottom_total","squeeze_risk","continuation_quality",
 "v4414_m2_watch_hours","v4414_m2_entry_below_support_atr",
 "v4414_m2_failed_reclaim_attempts","v4414_m2_retest_attempts",
 "v4414_m2_pivot_high_count","v4414_m2_bars_below"
]

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
      "fills":len(vals),"positive":sum(x>0 for x in vals),
      "positive_pct":_pct(sum(x>0 for x in vals),len(vals)),
      "net_expectancy_r":round(float(np.mean(vals)),5) if vals else None,
      "profit_factor":_pf(vals),"total_net_r":round(sum(vals),5)
    }

def _dist(rows,key):
    vals=[x for x in (_num(r.get(key)) for r in rows) if x is not None]
    if not vals:return {"n":0}
    a=np.asarray(vals,float)
    return {
      "n":len(vals),"mean":round(float(a.mean()),5),"median":round(float(np.median(a)),5),
      "p25":round(float(np.percentile(a,25)),5),"p75":round(float(np.percentile(a,75)),5)
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
        if int(r.get("market_risk_off") or 0)!=1:continue
        if int(r.get("s4_macro_bear") or 0)!=1:continue
        x=dict(r); x["_entry_ts"]=pd.Timestamp(r["v4414_m2_entry_time"]); out.append(x)
    return sorted(out,key=lambda r:r["_entry_ts"])

def _block_index(ts,start):
    return int((ts-start)/pd.Timedelta(days=60))+1

def _feature_contrast(good,bad,key):
    gd=_dist(good,key); bd=_dist(bad,key)
    gm=gd.get("median"); bm=bd.get("median")
    return {
      "good":gd,"bad":bd,
      "median_delta_good_minus_bad":None if gm is None or bm is None else round(gm-bm,5)
    }

def _gate_report(rows,name,pred):
    yes=[r for r in rows if pred(r)]
    no=[r for r in rows if not pred(r)]
    return {"name":name,"coverage_pct":_pct(len(yes),len(rows)),"yes":_metrics(yes),"no":_metrics(no)}

def main():
    src=sys.argv[1] if len(sys.argv)>1 else "artifact/v4414_m2_backtest.json"
    outdir=sys.argv[2] if len(sys.argv)>2 else "output"
    with open(src,"r",encoding="utf-8") as f: report=json.load(f)
    start=pd.Timestamp(report["period_start"])
    if start.tzinfo is None:start=start.tz_localize("UTC")

    rows=_entries(report)
    if len(rows)!=68:raise RuntimeError(f"Expected 68 V16-D entries, found {len(rows)}")
    for r in rows:r["_block"]=_block_index(r["_entry_ts"],start)

    good=[r for r in rows if r["_block"] in (1,2,3)]
    bad=[r for r in rows if r["_block"] in (4,5)]
    holdout=[r for r in rows if r["_block"]==6]

    contrasts={k:_feature_contrast(good,bad,k) for k in FEATURES}

    # Simple, interpretable, predeclared third-gate hypotheses based on V15 diagnostics.
    gates=[
      _gate_report(rows,"CONTEXT_GE_4",lambda r:(_num(r.get("candidate_context_points")) or -999)>=4),
      _gate_report(rows,"EMA_DISTANCE_GE_0_85",lambda r:(_num(r.get("ema20_distance_atr")) or -999)>=0.85),
      _gate_report(rows,"EMA_DISTANCE_GE_1_36",lambda r:(_num(r.get("ema20_distance_atr")) or -999)>=1.36),
      _gate_report(rows,"RANGE24_LE_0_345",lambda r:_num(r.get("range_position_24h")) is not None and float(r["range_position_24h"])<=0.345),
      _gate_report(rows,"RANGE24_LE_0_214",lambda r:_num(r.get("range_position_24h")) is not None and float(r["range_position_24h"])<=0.214),
      _gate_report(rows,"ANTI_BOTTOM_GE_10",lambda r:(_num(r.get("anti_bottom_total")) or -999)>=10),
      _gate_report(rows,"ANTI_BOTTOM_GE_17",lambda r:(_num(r.get("anti_bottom_total")) or -999)>=17),
      _gate_report(rows,"SQUEEZE_LE_3",lambda r:_num(r.get("squeeze_risk")) is not None and float(r["squeeze_risk"])<=3),
      _gate_report(rows,"MARKET_R4_LT_0",lambda r:_num(r.get("market_r4_pct")) is not None and float(r["market_r4_pct"])<0),
      _gate_report(rows,"REL4_LT_0",lambda r:_num(r.get("relative_4h_pct")) is not None and float(r["relative_4h_pct"])<0),
    ]

    # Same gates measured separately inside good/bad regime, to avoid a gate looking
    # strong merely because it selects mostly old good-regime trades.
    regime_gate_checks=[]
    gate_defs=[
      ("CONTEXT_GE_4",lambda r:(_num(r.get("candidate_context_points")) or -999)>=4),
      ("EMA_DISTANCE_GE_0_85",lambda r:(_num(r.get("ema20_distance_atr")) or -999)>=0.85),
      ("EMA_DISTANCE_GE_1_36",lambda r:(_num(r.get("ema20_distance_atr")) or -999)>=1.36),
      ("RANGE24_LE_0_345",lambda r:_num(r.get("range_position_24h")) is not None and float(r["range_position_24h"])<=0.345),
      ("ANTI_BOTTOM_GE_10",lambda r:(_num(r.get("anti_bottom_total")) or -999)>=10),
      ("ANTI_BOTTOM_GE_17",lambda r:(_num(r.get("anti_bottom_total")) or -999)>=17),
      ("SQUEEZE_LE_3",lambda r:_num(r.get("squeeze_risk")) is not None and float(r["squeeze_risk"])<=3),
    ]
    for name,pred in gate_defs:
        regime_gate_checks.append({
          "name":name,
          "good_yes":_metrics([r for r in good if pred(r)]),
          "bad_yes":_metrics([r for r in bad if pred(r)]),
          "good_coverage_pct":_pct(sum(pred(r) for r in good),len(good)),
          "bad_coverage_pct":_pct(sum(pred(r) for r in bad),len(bad)),
        })

    analysis={
      "status":"RESEARCH_ONLY","version":"V4.4.17","new_rule_promoted":False,
      "primary_cohort":"RISK_OFF AND S4_MACRO_BEAR",
      "counts":{"all":len(rows),"good_blocks_1_3":len(good),"bad_blocks_4_5":len(bad),"block6_holdout_sparse":len(holdout)},
      "metrics":{"all":_metrics(rows),"good":_metrics(good),"bad":_metrics(bad),"holdout_sparse":_metrics(holdout)},
      "feature_contrasts":contrasts,
      "third_gate_hypotheses_all_360d":gates,
      "third_gate_good_vs_bad":regime_gate_checks,
      "note":"Block 6 has only one primary-candidate trade and is excluded from good-vs-bad feature contrast."
    }
    os.makedirs(outdir,exist_ok=True)
    with open(os.path.join(outdir,"v4417_m2_failure_regime_study.json"),"w",encoding="utf-8") as f:
        json.dump(analysis,f,ensure_ascii=False,indent=2)
    with open(os.path.join(outdir,"v4417_m2_failure_regime_study.md"),"w",encoding="utf-8") as f:
        f.write("# V4.4.17 M2 — Failure Regime Study\n\n")
        f.write(json.dumps(analysis,ensure_ascii=False,indent=2))
    print(json.dumps(analysis,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
