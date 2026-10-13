"""M4 H3 forward outcome settlement: append-only, strictly AFTER snapshot registration.

Outcomes are computed on historic MEXC candles when 60h has passed. Capture
records can never be overwritten. No trades, no telegram and no entry advice.
"""
import hashlib,json,math,os
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
from .provider import fetch_hourly_paced
from .protocol import (
 HYPOTHESIS_ID,PROTOCOL_HASH,EVALUATE_AFTER_HOURS,HORIZONS_HOURS,
 FREEZE_START_UTC,
)
H=pd.Timedelta(hours=1)

def _utc(ts):
    t=pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

def future_outcomes(frame,entry_open,horizons=HORIZONS_HOURS):
    entry=_utc(entry_open)
    if frame is None or frame.empty or entry not in frame.index:return None
    anchor=float(frame.loc[entry,"open"])
    if not math.isfinite(anchor) or anchor<=0:return None
    out={"reference_entry_open":anchor}
    for h in horizons:
        stamps=[entry+j*H for j in range(int(h))]
        if any(t not in frame.index for t in stamps):return None
        f=frame.loc[stamps]
        exit_close=float(f.iloc[-1]["close"])
        lo=float(f["low"].min());hi=float(f["high"].max())
        out[f"short_{h}h_pct"]=round((anchor-exit_close)/anchor*100,6)
        out[f"mfe_{h}h_pct"]=round((anchor-lo)/anchor*100,6)
        out[f"mae_{h}h_pct"]=round((hi-anchor)/anchor*100,6)
    return out

def settle_batch(snapshot,now,fetch_fn=fetch_hourly_paced):
    now=_utc(now)
    if snapshot["protocol_hash"]!=PROTOCOL_HASH or snapshot["hypothesis_id"]!=HYPOTHESIS_ID:
        raise RuntimeError("Attempted outcome settlement on foreign protocol.")
    if _utc(snapshot["signal_time_utc"])<_utc(FREEZE_START_UTC):
        raise RuntimeError("Pre-freeze H3 batch forbidden")
    if snapshot.get("outcome_data_present") is not False:
        raise RuntimeError("Capture snapshot unexpectedly contains outcome data")
    if snapshot["status"]!="REGISTERED" or not snapshot["capture_before_virtual_entry"]:
        raise RuntimeError("Invalid capture cannot become prospective evidence")
    signal=_utc(snapshot["signal_time_utc"])
    captured=_utc(snapshot["run_finished_at_utc"])
    entry=_utc(snapshot["virtual_entry_reference_utc"])
    if captured>=entry:
        raise RuntimeError("H3 prospective capture occurred after virtual reference entry")
    if now<signal+pd.Timedelta(hours=EVALUATE_AFTER_HOURS):
        return None
    until=entry+(max(HORIZONS_HOURS)-1)*H
    all_symbols=set()
    for case in snapshot.get("h3_cases",[]):
        all_symbols.add(case["symbol"])
        all_symbols.update(case.get("control_symbols",[]))
    market={};fetch_errors={}
    for sym in sorted(all_symbols):
        try:
            f,_=fetch_fn(sym,entry,until)
            market[sym]=future_outcomes(f,entry)
            if market[sym] is None:fetch_errors[sym]="MISSING_COMPLETE_48H_OUTCOMES"
        except Exception as exc:
            market[sym]=None;fetch_errors[sym]=str(exc)[:240]
    if all_symbols and len(fetch_errors)/len(all_symbols)>.20:
        raise RuntimeError("Too many settlement errors, do not freeze potentially transient failures")

    rows=[]
    for e in snapshot.get("h3_cases",[]):
        c=market.get(e["symbol"])
        cs=[(sym,market.get(sym)) for sym in e.get("control_symbols",[])]
        controls=[z for _,z in cs if z is not None]
        row={
            "symbol":e["symbol"],"signal_time_utc":e["signal_time_utc"],
            "entry_reference_open_utc":entry.isoformat(),
            "status":"OK" if c is not None else "CASE_OUTCOME_UNAVAILABLE",
            "matched_control_count":len(controls),
            "matched_control_symbols":[s for s,z in cs if z is not None],
            "h3_capture_features":{k:e[k] for k in (
                "prior18_pct","last6_pct","relative6_pp","return24_pct",
                "asof_quote_turnover24_usdt") if k in e},
        }
        if c is not None:
            row.update(c)
            if controls:
                for h in HORIZONS_HOURS:
                    key=f"short_{h}h_pct"
                    ctrl=sum(x[key] for x in controls)/len(controls)
                    row[f"matched_control_short_{h}h_pct"]=round(ctrl,6)
                    row[f"paired_edge_{h}h_pp"]=round(c[key]-ctrl,6)
        rows.append(row)
    result={
        "protocol_hash":PROTOCOL_HASH,"hypothesis_id":HYPOTHESIS_ID,
        "source_batch_id":snapshot["batch_id"],
        "source_snapshot_sha256":hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest(),
        "source_signal_time_utc":signal.isoformat(),
        "capture_finished_before_entry":captured<entry,
        "settled_at_utc":now.isoformat(),
        "outcome_status":"COMPLETE" if not fetch_errors else "PARTIAL_WITH_ATTRITION",
        "outcome_count":len(rows),
        "outcome_rows":rows,"market_errors":fetch_errors,
        "source_kind":"MEXC_HISTORICAL_1H_NO_REAL_FILL",
        "research_only":True,
        "no_short_orders":True,"no_entry_ranking":True,
    }
    return result

def main():
    root=Path("state/m4_forward")
    snaps=sorted((root/"snapshots").glob("m4-h3-*.json")) if (root/"snapshots").is_dir() else []
    now=pd.Timestamp.now(tz="UTC")
    out_dir=root/"outcomes"
    out_dir.mkdir(parents=True,exist_ok=True)
    stats={"archived_snapshots":len(snaps),"already_settled":0,
           "not_mature":0,"invalid_capture":0,"created":0,"new_outcomes":[]}
    for path in snaps:
        output=out_dir/path.name
        if output.exists():stats["already_settled"]+=1;continue
        s=json.loads(path.read_text(encoding="utf-8"))
        if s.get("status")!="REGISTERED":
            stats["invalid_capture"]+=1;continue
        if now<_utc(s["signal_time_utc"])+pd.Timedelta(hours=EVALUATE_AFTER_HOURS):
            stats["not_mature"]+=1;continue
        data=settle_batch(s,now)
        if data is None:stats["not_mature"]+=1;continue
        output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        stats["created"]+=1;stats["new_outcomes"].append(str(output))
        if stats["created"]>=6:break # bounded load; later runs catch up
    Path("output/m4_forward").mkdir(parents=True,exist_ok=True)
    Path("output/m4_forward/settlement_audit.json").write_text(json.dumps(stats,indent=2),encoding="utf-8")
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
