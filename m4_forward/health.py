"""M4 V0.2.4: operational health of H3 point-in-time forward registry.

NO prices, PnL, TP/SL, H3 edge, performance summaries, backtest, or trading.
Audit that immutable H3 observations were registered ON TIME and hourly
sampling slots are not silently missed.
"""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json
import pandas as pd
from .protocol import (
    HYPOTHESIS_ID,PROTOCOL_HASH,FREEZE_START_UTC,CAPTURE_INTERVAL_HOURS,
)
from .settle import _utc

GRACE_HOURS=2 # operational only; do NOT manufacture a missed observation
MAX_EXAMPLES=12

def inventory(now=None,root=Path("state/m4_forward")):
    now=_utc(now or datetime.now(timezone.utc))
    start=_utc(FREEZE_START_UTC)
    lock=root/"H3_protocol_lock.json"
    if not lock.exists():raise RuntimeError("H3 preregistration lock missing")
    prereg=json.loads(lock.read_text(encoding="utf-8"))
    if prereg["protocol_sha256"]!=PROTOCOL_HASH or prereg["hypothesis_id"]!=HYPOTHESIS_ID:
        raise RuntimeError("Wrong or changed H3 preregistration")
    if _utc(prereg["locked_at_utc"])>=start:
        raise RuntimeError("Preregistration created after freeze start")

    snapshots={};invalid=[];present=[]
    snapdir=root/"snapshots"
    for p in sorted(snapdir.glob("m4-h3-*.json")) if snapdir.is_dir() else []:
        s=json.loads(p.read_text(encoding="utf-8"))
        batch=s.get("batch_id")
        if (s.get("hypothesis_id")!=HYPOTHESIS_ID or
            s.get("protocol_hash")!=PROTOCOL_HASH or
            s.get("outcome_data_present") is not False or
            p.name!=s.get("output_filename") or
            p.name!=f"m4-h3-{batch}.json"):
            raise RuntimeError(f"Invalid immutable snapshot metadata: {p.name}")
        signal=_utc(s["signal_time_utc"])
        if (signal<start or signal.hour%CAPTURE_INTERVAL_HOURS!=0 or
            signal.minute!=0 or signal.second!=0):
            raise RuntimeError(f"Off-cadence H3 snapshot: {p.name}")
        if batch in snapshots:
            raise RuntimeError(f"Duplicate archived H3 UTC time: {batch}")
        snapshots[batch]=s
        entry=_utc(s["virtual_entry_reference_utc"])
        finished=_utc(s["run_finished_at_utc"])
        if s["status"]=="REGISTERED":
            if not s.get("capture_before_virtual_entry") or finished>=entry:
                raise RuntimeError(f"Registered late signal: {p.name}")
            present.append((signal,s))
        else:
            invalid.append((signal,s["status"]))
        outcome=root/"outcomes"/p.name
        if outcome.exists():
            o=json.loads(outcome.read_text(encoding="utf-8"))
            expected=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()
            if (o.get("source_snapshot_sha256")!=expected or
                o.get("protocol_hash")!=PROTOCOL_HASH or
                o.get("source_batch_id")!=batch):
                raise RuntimeError(f"Invalid outcome/snapshot linkage: {p.name}")

    # Expected 4h canonical slots are judged only after 2h operational grace.
    missed=[]
    current=start
    cutoff=now-pd.Timedelta(hours=GRACE_HOURS)
    while current<=cutoff:
        b=current.strftime("%Y%m%dT%HZ")
        if b not in snapshots:missed.append(current.isoformat())
        current+=pd.Timedelta(hours=CAPTURE_INTERVAL_HOURS)
    outcomesdir=root/"outcomes"
    outcomes=len(list(outcomesdir.glob("m4-h3-*.json"))) if outcomesdir.is_dir() else 0
    newest=max((t for t,_ in present),default=None)
    if now<start:status="NOT_STARTED"
    elif not present:status="NO_VALID_SNAPSHOTS"
    elif missed:status="CAPTURE_GAPS_DETECTED"
    else:status="CAPTURE_ARCHIVE_PRESENT"
    return {
        "engine":"M4 V0.2.4 H3 Non-performance Reliability Audit",
        "status":status,
        "audit_asof_utc":now.isoformat(),
        "protocol_hash":PROTOCOL_HASH,
        "hypothesis_id":HYPOTHESIS_ID,
        "research_only":True,
        "performance_visible":False,
        "live_promotion":False,
        "expected_matured_capture_slots":len(snapshots)+len(missed) -
            sum(1 for s in snapshots.values() if _utc(s["signal_time_utc"])>cutoff),
        "missing_slots_after_grace":len(missed),
        "missing_utc_examples":missed[-MAX_EXAMPLES:],
        "valid_captures":len(present),
        "invalid_captures":len(invalid),
        "invalid_recent_examples":[{"signal_time_utc":t.isoformat(),"reason":reason}
            for t,reason in invalid[-MAX_EXAMPLES:]],
        "outcome_files_present_no_content_viewed":outcomes,
        "most_recent_valid_capture_utc":newest.isoformat() if newest is not None else None,
        "most_recent_valid_age_hours":round((now-newest).total_seconds()/3600,3) if newest is not None else None,
        "no_backfill_policy":"Absent snapshots never converted to historical H3 signals",
    }

def main():
    r=inventory()
    path=Path("output/m4_forward/health.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False,indent=2))
    return 0 # Signal gaps are health issues not failed hypothesis performance.

if __name__=="__main__":raise SystemExit(main())
