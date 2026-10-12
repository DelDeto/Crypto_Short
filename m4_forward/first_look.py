"""First-look lock for M4 H3. ZERO performance peeking before 60 days.

If sample is too small, the 60d conclusion is INCONCLUSIVE and an optional
single 120d evaluation can be run later, without modifying rules.
No automatic strategy promotion, entry/SL/TP, trading, or Telegram.
"""
from collections import defaultdict,Counter
from datetime import timedelta,datetime,timezone
from pathlib import Path
import json,random,statistics
import pandas as pd
from .protocol import (
 FREEZE_START_UTC,HYPOTHESIS_ID,PROTOCOL_HASH,MIN_CALENDAR_DAYS_FIRST_LOOK,
 MIN_MATCHED_EVENTS_FIRST_LOOK,MIN_UNIQUE_SIGNAL_DAYS_FIRST_LOOK,
 COST_STRESS_ROUND_TRIP_BPS,
)
from .settle import _utc

def _avg(xs):
    xs=[float(x) for x in xs]
    return round(statistics.fmean(xs),6) if xs else None

def _ci_by_day(rows,reps=2000):
    by_day=defaultdict(list)
    for r in rows:by_day[r["signal_time_utc"][:10]].append(float(r["paired_edge_48h_pp"]))
    days=sorted(by_day)
    if len(days)<5:return [None,None]
    rng=random.Random(423);means=[]
    for _ in range(reps):
        chosen=[days[rng.randrange(len(days))] for _ in days]
        means.append(statistics.fmean(x for d in chosen for x in by_day[d]))
    means.sort()
    return [round(means[int(.025*(reps-1))],6),
            round(means[int(.975*(reps-1))],6)]

def evaluation(now,root=Path("state/m4_forward"),duration_days=60):
    now=_utc(now);freeze=_utc(FREEZE_START_UTC)
    end=freeze+pd.Timedelta(days=duration_days)
    if now<end+pd.Timedelta(hours=60):
        return {"status":"ACCUMULATING_NO_PERFORMANCE_EVALUATION","duration_days":duration_days,
                "earliest_evaluation_after_utc":(end+pd.Timedelta(hours=60)).isoformat()}
    snaps=[];outs=[]
    for p in sorted((root/"snapshots").glob("m4-h3-*.json")):
        s=json.loads(p.read_text(encoding="utf-8"))
        t=_utc(s["signal_time_utc"])
        if not freeze<=t<end:continue
        if s["protocol_hash"]!=PROTOCOL_HASH or s["hypothesis_id"]!=HYPOTHESIS_ID:
            raise RuntimeError("Mixed future protocol")
        if s["status"]!="REGISTERED":continue
        snaps.append(s)
        op=root/"outcomes"/p.name
        if op.exists():
            o=json.loads(op.read_text(encoding="utf-8"))
            if o["source_batch_id"]!=s["batch_id"] or o["protocol_hash"]!=PROTOCOL_HASH:
                raise RuntimeError("Mismatched or changed forward outcome")
            outs.append(o)
    if not snaps:
        return {"status":"INCONCLUSIVE_NO_VALID_PROSPECTIVE_SNAPSHOTS","duration_days":duration_days}
    outcome_coverage=len(outs)/len(snaps)
    if outcome_coverage<.95:
        return {"status":"OUTCOME_COLLECTION_INCOMPLETE_NO_TEST","coverage_ratio":round(outcome_coverage,4),
                "snapshots":len(snaps),"outcomes":len(outs)}
    rows=[r for o in outs for r in o["outcome_rows"] if r.get("status")=="OK" and r.get("matched_control_count",0)>=1 and "paired_edge_48h_pp" in r]
    days=len({r["signal_time_utc"][:10] for r in rows})
    if len(rows)<MIN_MATCHED_EVENTS_FIRST_LOOK or days<MIN_UNIQUE_SIGNAL_DAYS_FIRST_LOOK:
        return {"status":"INCONCLUSIVE_SAMPLE_TOO_SMALL","duration_days":duration_days,
                "matched_events":len(rows),"unique_days":days,
                "next_pre_registered_look_days":120 if duration_days==60 else None}
    pp=[float(r["paired_edge_48h_pp"]) for r in rows]
    short=[float(r["short_48h_pct"]) for r in rows]
    day_ci=_ci_by_day(rows)
    # Descriptive 20bps execution cost sensitivity, NOT claims on real fees.
    net=[x-COST_STRESS_ROUND_TRIP_BPS/100 for x in short]
    positives=sum(statistics.fmean(v)>0 for v in
        ([float(r["paired_edge_48h_pp"]) for r in rows if r["signal_time_utc"][:10]==d]
         for d in {r["signal_time_utc"][:10] for r in rows}))
    evidence={
        "matched_events":len(rows),"unique_signal_days":days,
        "mean_raw_short_48h_pct":_avg(short),
        "mean_short_48h_minus_20bps_sensitivity":_avg(net),
        "mean_paired_edge_48h_pp":_avg(pp),
        "day_cluster_bootstrap_95_descriptive":day_ci,
        "positive_days":positives,"positive_day_fraction":round(positives/days,4),
        "tail_raw_short_p05_pct":round(sorted(short)[int(.05*len(short))],6),
    }
    supportive=bool(
        evidence["mean_short_48h_minus_20bps_sensitivity"]>0 and
        evidence["mean_paired_edge_48h_pp"]>0 and
        day_ci[0] is not None and day_ci[0]>0 and
        evidence["positive_day_fraction"]>=.60
    )
    return {
        "status":"DESCRIPTIVE_SUPPORTIVE_NOT_TRADABLE" if supportive else "NOT_CONFIRMED",
        "duration_days":duration_days,
        "research_only":True,"not_untouched_historical_backtest":True,
        "needs_execution_cost_and_independent_replication":True,
        "live_promotion":False,"statistics":evidence,
        "outcome_coverage":round(outcome_coverage,5),
        "snapshot_count":len(snaps),"matched_control_selection":"frozen at capture",
    }

def main():
    root=Path("state/m4_forward");out=root/"studies";out.mkdir(parents=True,exist_ok=True)
    now=pd.Timestamp.now(tz="UTC")
    first=out/"H3_first_60d.json"
    if first.exists():
        result=json.loads(first.read_text(encoding="utf-8"))
        print("Immutable 60d first-look already filed:",result["status"]);return 0
    result=evaluation(now,root,60)
    status=result["status"]
    # Never write ongoing performance; only file one immutable conclusion when mature.
    if status not in ("ACCUMULATING_NO_PERFORMANCE_EVALUATION",
                     "OUTCOME_COLLECTION_INCOMPLETE_NO_TEST"):
        first.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="statistics"},indent=2,ensure_ascii=False))
    return 0

if __name__=="__main__":raise SystemExit(main())
