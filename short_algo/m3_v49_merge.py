"""M3 V4.9.1: prospective replay audit, immutable per-trade ledger and shadow-only gates."""
import csv,hashlib,json,os,sys
from glob import glob
from datetime import datetime
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_ELIGIBLE_SYMBOLS
from .m3_v46_merge import _metrics,_pct
from .m3_v49_config import (
    M3_V49_FORWARD_START,M3_V49_FREEZE_COMMIT,M3_V49_EVIDENCE_CLASS,
    M3_V49_SHALLOW_RETEST_MAX_ATR15,M3_V49_MIN_FORWARD_DAYS,
    M3_V49_MIN_H1_ENTRIES,M3_V49_MIN_ACTIVE_BLOCKS,
    M3_V49_MIN_POSITIVE_BLOCK_FRACTION,
)

def _match_h1(row):
    v=row.get("m3v21_retest_penetration_atr15")
    return v is not None and float(v)<=float(M3_V49_SHALLOW_RETEST_MAX_ATR15)

def _valid_exit(row):
    return int((row.get("m3v45_frozen_exit") or {}).get("valid") or 0)==1

def _readiness(h1,forward_days):
    active=int(h1.get("active_blocks") or 0)
    positive=int(h1.get("positive_expectancy_blocks") or 0)
    pos_frac=(positive/active) if active else 0.0
    checks={
        "min_forward_days":float(forward_days)>=float(M3_V49_MIN_FORWARD_DAYS),
        "min_h1_entries":int(h1.get("entries") or 0)>=int(M3_V49_MIN_H1_ENTRIES),
        "min_active_blocks":active>=int(M3_V49_MIN_ACTIVE_BLOCKS),
        "positive_block_fraction":pos_frac>=float(M3_V49_MIN_POSITIVE_BLOCK_FRACTION),
    }
    return {"ready":all(checks.values()),"checks":checks,"positive_block_fraction":round(pos_frac,4)}

def _edge_checks(h1,baseline):
    ci=h1.get("expectancy_bootstrap95_r") or [None,None]
    lo=ci[0] if len(ci)>0 else None
    checks={
        "expectancy_positive":h1.get("expectancy_r") is not None and float(h1["expectancy_r"])>0,
        "expectancy_beats_baseline":h1.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None and float(h1["expectancy_r"])>float(baseline["expectancy_r"]),
        "drawdown_not_worse":h1.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None and float(h1["max_drawdown_r_signal_order"])<=float(baseline["max_drawdown_r_signal_order"]),
    }
    return {
        "pass":all(checks.values()),
        "checks":checks,
        "nominal_bootstrap_ci_excludes_zero":lo is not None and float(lo)>0,
        "multiple_looks_adjusted":False,
    }

def _trade_ledger(rows,m):
    start=datetime.fromisoformat(m["period_start"])
    end=datetime.fromisoformat(m["period_end"])
    ledger=[]
    for r in sorted(rows,key=lambda x:(x.get("signal_time") or "",x.get("symbol") or "")):
        ts=datetime.fromisoformat(r["signal_time"])
        if not start<=ts<end:
            raise RuntimeError(f"Pre-freeze or out-of-window trade: {r.get('symbol')} {ts.isoformat()}")
        if not _valid_exit(r):continue
        k=f"{r['symbol']}|{ts.isoformat()}"
        ex=r.get("m3v45_frozen_exit") or {}
        ledger.append({
            "signal_id":hashlib.sha256(k.encode()).hexdigest()[:20],
            "symbol":r.get("symbol"),"signal_time_utc":ts.isoformat(),
            "block":r.get("m3v45_block"),
            "h1_shallow_retest":int(_match_h1(r)),
            "retest_penetration_atr15":r.get("m3v21_retest_penetration_atr15"),
            "outcome_state":ex.get("state"),
            "outcome_r":ex.get("result_r"),
            "outcome_minutes":ex.get("minutes"),
            "data_source":"MEXC_historical_replay",
            "evidence_class":M3_V49_EVIDENCE_CLASS,
        })
    return ledger

def main(root="m3v49_shards",preflight_path="frozen/m3_v49_preflight.json"):
    reps=[]
    for p in sorted(glob(os.path.join(root,"**","m3_v49_backtest.json"),recursive=True)):
        with open(p,encoding="utf-8") as f:reps.append(json.load(f))
    if not reps:raise RuntimeError("No M3 V4.9.1 shard reports")
    expected=max(int(r["shard_count"]) for r in reps)
    found={int(r["shard_index"]) for r in reps}
    if len(reps)!=expected or found!=set(range(expected)):
        raise RuntimeError(f"Missing/duplicated shard reports: {len(reps)} vs {expected}, indices={sorted(found)}")
    mids={r["manifest_id"] for r in reps}
    if len(mids)!=1:raise RuntimeError("Mixed manifest IDs")
    if not os.path.isfile(preflight_path):raise RuntimeError("Missing preflight evidence")
    with open(preflight_path,encoding="utf-8") as f:preflight=json.load(f)

    m=reps[0]["manifest"]
    if not m.get("window_ready") or m.get("manifest_status")!="READY_FOR_REPLAY":
        raise RuntimeError("Attempted replay merge before mature forward window")
    if m["period_start"]!=M3_V49_FORWARD_START or m.get("research_freeze_commit")!=M3_V49_FREEZE_COMMIT:
        raise RuntimeError("Prospective evidence anchor changed")
    if m.get("evidence_class")!=M3_V49_EVIDENCE_CLASS:
        raise RuntimeError("Evidence class mismatch")
    if any(r.get("manifest")!=m for r in reps):
        raise RuntimeError("Shard manifests differ")
    if preflight.get("manifest_id")!=m["manifest_id"] or not preflight.get("data_valid"):
        raise RuntimeError("Preflight manifest mismatch or invalid preflight")

    dedup={};coverage=[];errors=[];symbols=[]
    for r in reps:
        coverage.extend(r.get("coverage",[]))
        errors.extend(r.get("errors",[]))
        symbols.extend(r.get("selected_symbols",[]))
        for row in r.get("rows",[]):
            key=(row.get("symbol"),row.get("signal_time"))
            if key in dedup:
                raise RuntimeError(f"Duplicate signal key across shards: {key}")
            dedup[key]=row
    rows=list(dedup.values())
    cov={c.get("symbol"):c for c in coverage}
    eligible=sum(1 for c in cov.values() if int(c.get("eligible") or 0)==1)
    data_valid=bool(
        eligible>=int(M3_V441_MIN_ELIGIBLE_SYMBOLS)
        and len(set(symbols))==len(m["symbols"])
        and set(symbols)==set(m["symbols"])
        and not errors
    )

    blocks=m["blocks"];forward_days=float(m["forward_days"])
    ledger=_trade_ledger(rows,m)
    baseline=_metrics(rows,forward_days,blocks)
    h1=_metrics([r for r in rows if _match_h1(r)],forward_days,blocks)
    if baseline["entries"]!=len(ledger) or h1["entries"]!=sum(int(x["h1_shallow_retest"]) for x in ledger):
        raise RuntimeError("Ledger and outcome metrics disagree")
    readiness=_readiness(h1,forward_days)
    edge=_edge_checks(h1,baseline)
    if not data_valid:
        decision="DATA_INVALID_DO_NOT_INTERPRET"
    elif not readiness["ready"]:
        decision="ACCUMULATING_PROSPECTIVE_EVIDENCE"
    elif edge["pass"] and edge["nominal_bootstrap_ci_excludes_zero"]:
        decision="PROSPECTIVE_SHADOW_SUPPORTIVE_CI_DESCRIPTIVE"
    elif edge["pass"]:
        decision="PROSPECTIVE_SHADOW_DIRECTIONAL_ONLY_CI_WIDE"
    else:
        decision="PROSPECTIVE_SHADOW_NOT_CONFIRMED"

    comparison={
        "retained_pct":_pct(h1["entries"],baseline["entries"]),
        "delta_expectancy_r":round(float(h1["expectancy_r"])-float(baseline["expectancy_r"]),5) if h1.get("expectancy_r") is not None and baseline.get("expectancy_r") is not None else None,
        "delta_max_drawdown_r":round(float(h1["max_drawdown_r_signal_order"])-float(baseline["max_drawdown_r_signal_order"]),5) if h1.get("max_drawdown_r_signal_order") is not None and baseline.get("max_drawdown_r_signal_order") is not None else None,
    }
    out={
        "engine":"M3 V4.9.1 Shallow Retest Prospective Replay Audit",
        "manifest_id":m["manifest_id"],
        "period_start":m["period_start"],"period_end":m["period_end"],
        "forward_days":forward_days,
        "selected_symbols":len(set(symbols)),"eligible_symbols":eligible,
        "data_valid":data_valid,"errors":errors,"preflight":preflight,
        "evidence_class":M3_V49_EVIDENCE_CLASS,
        "research_freeze_commit":M3_V49_FREEZE_COMMIT,
        "legacy_oct05_window_excluded":True,
        "hypothesis_frozen_before_forward_run":m.get("hypothesis"),
        "baseline":baseline,"h1_shallow_retest":h1,
        "h1_vs_baseline":comparison,"readiness_gate":readiness,"edge_gate":edge,
        "trade_ledger_count":len(ledger),
        "decision":decision,
        "live_promotion":False,
        "research_status":"PROSPECTIVE_REPLAY_SHADOW_ONLY" if data_valid else "DATA_INVALID",
        "limitations":[
            "No contemporaneous live signal ledger: outcomes reconstructed from later historical data.",
            "Repeated weekly looks are not adjusted for multiple testing; nominal bootstrap CI is descriptive.",
            "No inference about realized net PnL, exchange costs or portfolio fills from signal-order R metrics.",
        ],
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)
    ledger_path=os.path.join(OUTPUT_DIR,"m3_v49_trade_ledger.csv")
    fieldnames=[
        "signal_id","symbol","signal_time_utc","block","h1_shallow_retest",
        "retest_penetration_atr15","outcome_state","outcome_r","outcome_minutes",
        "data_source","evidence_class",
    ]
    with open(ledger_path,"w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames)
        writer.writeheader();writer.writerows(ledger)
    ledger_sha=hashlib.sha256(open(ledger_path,"rb").read()).hexdigest()
    out["trade_ledger_sha256"]=ledger_sha
    with open(os.path.join(OUTPUT_DIR,"m3_v49_analysis.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2,default=str)

    with open(os.path.join(OUTPUT_DIR,"m3_v49_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.9.1 - Prospective Shadow Evidence\n\n")
        f.write(f"**Decision:** {decision} (no live promotion)\n\n")
        f.write(f"**Start (post-freeze):** {m['period_start']} — **End:** {m['period_end']}\n\n")
        f.write(f"**Eligible symbols:** {eligible} — **Evidence:** {M3_V49_EVIDENCE_CLASS}\n\n")
        f.write("| Strategy | Trades | TP% | SL% | Exp (R) | Max DD (R) |\n|---|---:|---:|---:|---:|---:|\n")
        for label,met in (("Baseline",baseline),("H1 Shallow Retest",h1)):
            f.write(f"| {label} | {met['entries']} | {met['target_hit_pct']} | {met['sl_hit_pct']} | {met['expectancy_r']} | {met['max_drawdown_r_signal_order']} |\n")
        f.write(f"\nReadiness checks: \`{json.dumps(readiness['checks'])}\`\n\n")
        f.write("**Caveat:** Reconstructed historical-candle replay, not a timestamped live paper-trading ledger. CI not multiple-look adjusted.\n")
    print(json.dumps({
        "decision":decision,"data_valid":data_valid,"forward_days":forward_days,
        "eligible_symbols":eligible,"baseline":baseline,"h1":h1,
        "h1_vs_baseline":comparison,"readiness":readiness,"edge":edge,
        "ledger_rows":len(ledger),"ledger_sha256":ledger_sha,
    },ensure_ascii=False,indent=2))
    return 0 if data_valid else 2

if __name__=="__main__":
    root=sys.argv[1] if len(sys.argv)>1 else "m3v49_shards"
    pf=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v49_preflight.json"
    raise SystemExit(main(root,pf))
