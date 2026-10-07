"""V4.4.2 60-day validation for quality-tiered M1 and optimized M2."""
import json
import os
import sys
from collections import Counter
from glob import glob

import numpy as np
import pandas as pd

from .config import OUTPUT_DIR
from .v428_merge import _add_cross_section_and_phase
from .v441_execution import TERMINAL_STATES
from .v441_main import CSV_FIELDS, _write_csv, _write_json
from .v442_config import (
    V442_COOLDOWN_HOURS,
    V442_M1B_MAX_COST_R,
    V442_M1B_MIN_ROOM_R,
    V442_M1B_MIN_SCORE,
    V442_M2_MAX_BREAK_BODY_ATR,
    V442_M2_MAX_COST_R,
    V442_M2_MAX_ENTRY_BELOW_SUPPORT_ATR,
    V442_M2_MIN_ROOM_R,
    V442_M2_MIN_SCORE,
)


def _load(root):
    out=[]
    for path in sorted(glob(os.path.join(root, "**", "v442_backtest.json"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def _num(v):
    try:
        x=float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _pct(n,d):
    return round(100.0*n/d,2) if d else None


def _mean(vals):
    x=[v for v in (_num(z) for z in vals) if v is not None]
    return round(float(np.mean(x)),5) if x else None


def _pf(vals):
    x=[v for v in (_num(z) for z in vals) if v is not None]
    gains=sum(v for v in x if v>0)
    losses=-sum(v for v in x if v<0)
    if losses<=0:
        return 999.0 if gains>0 else None
    return round(gains/losses,4)


def _unique(rows):
    last={}
    out=[]
    for r in sorted(rows,key=lambda x:(str(x.get("signal_time")),str(x.get("symbol")))):
        s=str(r.get("symbol"))
        t=pd.Timestamp(r.get("signal_time"))
        if s in last and (t-last[s]) < pd.Timedelta(hours=int(V442_COOLDOWN_HOURS)):
            continue
        last[s]=t
        out.append(r)
    return out


def _is_terminal(row,prefix):
    return row.get(f"{prefix}_state") in TERMINAL_STATES and _num(row.get(f"{prefix}_net_r")) is not None


def _m1a_ok(row):
    return (
        row.get("v440_state") in TERMINAL_STATES
        and _num(row.get("v440_net_r")) is not None
    )


def _m1b_quality(row):
    phase=str(row.get("v428_trend_phase") or "")
    score=int(row.get("v441_m1_confirm_score") or 0)
    cost=_num(row.get("v441_m1_cost_r"))
    room=_num(row.get("v441_m1_room_r"))
    return bool(
        _is_terminal(row,"v441_m1")
        and phase in ("EARLY_DOWNTREND","MATURE_DOWNTREND")
        and score >= int(V442_M1B_MIN_SCORE)
        and int(row.get("v441_m1_failed_auction") or 0) == 1
        and (
            int(row.get("v441_m1_micro_bos") or 0) == 1
            or int(row.get("v441_m1_rejection") or 0) == 1
        )
        and cost is not None and cost <= float(V442_M1B_MAX_COST_R)
        and room is not None and room >= float(V442_M1B_MIN_ROOM_R)
    )


def _m2_quality(row):
    if not _is_terminal(row,"v441_m2"):
        return False
    phase=str(row.get("v428_trend_phase") or "")
    score=int(row.get("v441_m2_confirm_score") or 0)
    entry=_num(row.get("v441_m2_entry"))
    support=_num(row.get("v441_m2_support_level"))
    atr=_num(row.get("atr_1h"))
    cost=_num(row.get("v441_m2_cost_r"))
    room=_num(row.get("v441_m2_room_r"))
    body=_num(row.get("v441_m2_break_body_atr"))
    if None in (entry,support,atr,cost,room,body) or atr <= 0:
        return False
    entry_below=max(0.0,(support-entry)/atr)
    row["v442_m2_entry_below_support_atr"]=round(entry_below,4)
    return bool(
        phase in ("EARLY_DOWNTREND","MATURE_DOWNTREND")
        and score >= int(V442_M2_MIN_SCORE)
        and int(row.get("v441_m2_controlled_break") or 0) == 1
        and int(row.get("v441_m2_retest_touched") or 0) == 1
        and int(row.get("v441_m2_retest_rejection") or 0) == 1
        and entry_below <= float(V442_M2_MAX_ENTRY_BELOW_SUPPORT_ATR)
        and body <= float(V442_M2_MAX_BREAK_BODY_ATR)
        and cost <= float(V442_M2_MAX_COST_R)
        and room >= float(V442_M2_MIN_ROOM_R)
    )


def _metrics(rows,prefix):
    if prefix=="v440":
        fills=[r for r in rows if _m1a_ok(r)]
    else:
        fills=[r for r in rows if _is_terminal(r,prefix)]
    net=[float(r[f"{prefix}_net_r"]) for r in fills]
    gross=[float(r[f"{prefix}_gross_r"]) for r in fills if _num(r.get(f"{prefix}_gross_r")) is not None]
    states=Counter(str(r.get(f"{prefix}_state") or "NONE") for r in fills)
    return {
        "fills":len(fills),
        "positive_net":sum(v>0 for v in net),
        "positive_net_pct":_pct(sum(v>0 for v in net),len(net)),
        "stop_pct":_pct(sum(r.get(f"{prefix}_state")=="SL_FIRST" for r in fills),len(fills)),
        "tp1_hit_pct": (
            None if prefix=="v440"
            else _pct(sum(int(r.get(f"{prefix}_tp1_hit") or 0) for r in fills),len(fills))
        ),
        "tp2_demand_pct":_pct(sum(r.get(f"{prefix}_state")=="TP2_DEMAND" for r in fills),len(fills)),
        "ft_pass_pct": (
            None if prefix=="v440"
            else _pct(sum(int(r.get(f"{prefix}_ft_pass") or 0) for r in fills),len(fills))
        ),
        "gross_expectancy_r":_mean(gross),
        "net_expectancy_r":_mean(net),
        "profit_factor":_pf(net),
        "total_net_r":round(sum(net),5),
        "avg_cost_r":_mean([r.get(f"{prefix}_cost_r") for r in fills]),
        "avg_room_r":_mean([r.get(f"{prefix}_room_r") for r in fills]),
        "avg_risk_atr":_mean([r.get(f"{prefix}_risk_atr") for r in fills]),
        "states":dict(sorted(states.items())),
    }


def _gate(m):
    checks={
        "sample_fills_ge_20":int(m.get("fills") or 0)>=20,
        "net_expectancy_gt_0":m.get("net_expectancy_r") is not None and m["net_expectancy_r"]>0,
        "profit_factor_gt_1_05":m.get("profit_factor") is not None and m["profit_factor"]>1.05,
    }
    return {"checks":checks,"pass":all(checks.values())}


def _summary(report):
    a=report["analysis"]
    lines=[
        "# Crypto Short V4.4.2 — 60d Quality-Tier Research",
        "",
        f"- Period: {report['period_start']} -> {report['period_end']}",
        f"- Symbols: {report['selected_symbol_count']}",
        f"- Integrity: {'PASS' if report['manifest_integrity']['ok'] else 'FAIL'}",
        f"- Errors: {len(report['errors'])}",
        "- Research window intentionally limited to 60 days.",
        "",
        "## Cohorts",
        "- M1_A: strict V4.4 entry, quality-first baseline.",
        "- M1_B: V4.4.1 scored setup but only EARLY/MATURE phase, score>=4, failed auction, >=2.5R room and <=0.20R cost.",
        "- M2_OPT: EDGE-like breakdown with EARLY/MATURE phase, controlled break, actual retest+rejection, entry <=0.65 ATR below support, break body <=1.10 ATR, >=2.5R room and <=0.20R cost.",
        "",
        "| Cohort | Fills | Positive% | Stop% | TP1% | Gross R | Net R | PF | Avg Cost R | Avg Room R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key,label in (("M1_A","M1 A-grade strict"),("M1_B","M1 B-grade scored"),("M2_OPT","M2 optimized EDGE")):
        x=a["full_60d"][key]
        lines.append(
            f"| {label} | {x['fills']} | {x['positive_net_pct']} | {x['stop_pct']} | {x['tp1_hit_pct']} | "
            f"{x['gross_expectancy_r']} | {x['net_expectancy_r']} | {x['profit_factor']} | {x['avg_cost_r']} | {x['avg_room_r']} |"
        )
    lines += [
        "",
        "## Unique 96h episodes",
        f"- M1_A: {a['unique_96h']['M1_A']}",
        f"- M1_B: {a['unique_96h']['M1_B']}",
        f"- M2_OPT: {a['unique_96h']['M2_OPT']}",
        "",
        f"- Gates: {a['gates']}",
        "- This 60d run is a fast research iteration, not long-horizon validation.",
    ]
    return "\n".join(lines)


def merge_reports(reports):
    if not reports:
        raise RuntimeError("No V4.4.2 shard reports found")
    expected=max(int(r.get("shard_count") or 1) for r in reports)
    found={int(r.get("shard_index")) for r in reports}
    if found != set(range(expected)):
        raise RuntimeError(f"Incomplete V4.4.2 shards: {sorted(found)}")
    ids={str(r.get("manifest_id")) for r in reports}
    if len(ids)!=1:
        raise RuntimeError("V4.4.2 manifest mismatch")

    first=reports[0]
    frozen=set((first.get("manifest") or {}).get("symbols") or [])
    symbols=[]; raw=[]; errors=[]
    for r in reports:
        symbols.extend(r.get("selected_symbols") or [])
        raw.extend(r.get("trades") or [])
        errors.extend(r.get("errors") or [])
    uniq=set(symbols)
    integrity={
        "ok":len(reports)==expected and len(symbols)==len(uniq) and uniq==frozen,
        "expected_shards":expected,
        "found_shards":len(reports),
        "frozen_symbol_count":len(frozen),
        "merged_symbol_count":len(uniq),
    }
    if not integrity["ok"]:
        raise RuntimeError(f"V4.4.2 integrity failure: {integrity}")

    dedup={}
    for row in raw:
        dedup.setdefault((row.get("symbol"),row.get("signal_time")),row)
    rows=sorted(dedup.values(),key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    _add_cross_section_and_phase(rows)

    m1a=[r for r in rows if _m1a_ok(r)]
    m1b=[r for r in rows if _m1b_quality(r)]
    m2=[r for r in rows if _m2_quality(r)]

    m1a_u=_unique(m1a)
    m1b_u=_unique(m1b)
    m2_u=_unique(m2)

    full={
        "M1_A":_metrics(m1a,"v440"),
        "M1_B":_metrics(m1b,"v441_m1"),
        "M2_OPT":_metrics(m2,"v441_m2"),
    }
    unique={
        "M1_A":_metrics(m1a_u,"v440"),
        "M1_B":_metrics(m1b_u,"v441_m1"),
        "M2_OPT":_metrics(m2_u,"v441_m2"),
    }
    analysis={
        "counts":{
            "raw":len(rows),
            "m1_a_fills":len(m1a),
            "m1_b_fills":len(m1b),
            "m2_opt_fills":len(m2),
        },
        "full_60d":full,
        "unique_96h":unique,
        "gates":{
            "M1_A":_gate(unique["M1_A"]),
            "M1_B":_gate(unique["M1_B"]),
            "M2_OPT":_gate(unique["M2_OPT"]),
        },
        "research_status":"RESEARCH_ONLY",
        "fixed_parameter_run":True,
        "parameter_grid_searched":False,
    }
    return {
        "engine":"Crypto Short V4.4.2 60d Quality-Tier Research",
        "manifest_id":next(iter(ids)),
        "manifest":first.get("manifest"),
        "manifest_integrity":integrity,
        "period_start":first.get("period_start"),
        "period_end":first.get("period_end"),
        "days":first.get("days"),
        "selected_symbols":sorted(uniq),
        "selected_symbol_count":len(uniq),
        "analysis":analysis,
        "trades":rows,
        "errors":errors,
    }


def main():
    root=sys.argv[1] if len(sys.argv)>1 else "shard_outputs"
    report=merge_reports(_load(root))
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    _write_json(os.path.join(OUTPUT_DIR,"v442_backtest.json"),report)
    _write_json(os.path.join(OUTPUT_DIR,"v442_analysis.json"),report["analysis"])
    _write_json(os.path.join(OUTPUT_DIR,"v442_manifest.json"),report["manifest"])
    fields=CSV_FIELDS+[
        "v428_trend_phase","v428_structure_score","v428_exhaustion_score",
        "v428_recovery_score","v442_m2_entry_below_support_atr",
    ]
    _write_csv(os.path.join(OUTPUT_DIR,"v442_scored_candidates.csv"),report["trades"],fields=fields)
    with open(os.path.join(OUTPUT_DIR,"v442_summary.md"),"w",encoding="utf-8") as f:
        f.write(_summary(report))
    print(json.dumps({
        "integrity":report["manifest_integrity"],
        "errors":len(report["errors"]),
        "analysis":report["analysis"],
    },ensure_ascii=False,indent=2))
    return 0 if not report["errors"] else 2


if __name__=="__main__":
    sys.exit(main())
