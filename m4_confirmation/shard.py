"""M4 V0.2.2 shard: once-per-symbol historical replay of frozen H1 cases and controls."""
import hashlib,json,os,sys
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pandas as pd
from m4_audit.audit import load,validate
from m4_research.market import fetch_hourly
from .config import SHARD_COUNT,SOURCE_MANIFEST,CONFIRM_WITHIN_HOURS
from .engine import case_study,control_study,H

def _owner(symbol):
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:12],16)%SHARD_COUNT

def run(source="frozen/v02",manifest_path="frozen/v022/manifest.json",out="output/m4_v022/shard.json"):
    base=Path(source)/"output/m4"
    manifest=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest["source_manifest"]!=SOURCE_MANIFEST or manifest["shard_count"]!=SHARD_COUNT:
        raise RuntimeError("M4 H2 frozen manifest mismatch")
    idx=int(os.getenv("M4_V022_SHARD_INDEX","0"))
    if not 0<=idx<SHARD_COUNT:raise RuntimeError("Invalid shard index")
    expected_sha=manifest["source_file_sha256"]
    for fname,h in expected_sha.items():
        if hashlib.sha256((base/fname).read_bytes()).hexdigest()!=h:
            raise RuntimeError("Modified upstream M4 V0.2 source: "+fname)
    study=json.loads((base/"m4_study.json").read_text(encoding="utf-8"))
    old_manifest=json.loads((Path(source)/"frozen/m4/manifest.json").read_text(encoding="utf-8"))
    events=load(base/"m4_events.csv");pairs=load(base/"m4_matched_controls.csv")
    validate(events,pairs,study,old_manifest)

    case_map=defaultdict(list);control_map=defaultdict(set)
    for e in events:case_map[e["symbol"]].append(e)
    for p in pairs:
        event_time=p["signal_time_utc"]
        for control in p["control_symbols"].split(";"):
            if control:control_map[control].add(event_time)
    selected=[s for s in manifest["symbols"] if _owner(s)==idx]
    if not selected:raise RuntimeError("Empty shard")
    assert len(set(selected))==len(selected)
    now=pd.Timestamp.now(tz="UTC").floor("h")
    last_closed=now-H
    report={"manifest_id":manifest["manifest_id"],"shard_index":idx,
            "selected_symbols":selected,"cases":[],"controls":[],
            "symbol_audit":[],"requests":0}
    for j,sym in enumerate(selected,1):
        cases=case_map.get(sym,[])
        ctrl_times=sorted(control_map.get(sym,[]))
        times=[pd.Timestamp(e["signal_time_utc"]) for e in cases]+[pd.Timestamp(t) for t in ctrl_times]
        item={"symbol":sym,"case_count":len(cases),"control_times":len(ctrl_times)}
        try:
            start=min(times)-H # H1 trigger candle opens one hour before signal.
            finish=min(last_closed,max(times)+pd.Timedelta(hours=CONFIRM_WITHIN_HOURS+48))
            if start>=finish:raise RuntimeError("Empty data window")
            df,requests=fetch_hourly(sym,start,finish)
            item.update({"bars":len(df),"requests":requests})
            report["requests"]+=requests
            for e in cases:
                report["cases"].append(case_study(e,df,last_closed))
            for t in ctrl_times:
                for lag in range(1,CONFIRM_WITHIN_HOURS+1):
                    report["controls"].append(control_study(sym,t,lag,df,last_closed))
        except Exception as exc:
            item["error"]=str(exc)[:420]
            for e in cases:
                report["cases"].append({"symbol":sym,"event_signal_utc":e["signal_time_utc"],"confirmation_status":"FETCH_ERROR"})
            for t in ctrl_times:
                for lag in range(1,CONFIRM_WITHIN_HOURS+1):
                    report["controls"].append({"symbol":sym,"event_signal_utc":t,"lag_hours":lag,"outcome_status":"FETCH_ERROR"})
        report["symbol_audit"].append(item)
        if j%20==0 or j==len(selected):
            print(f"M4 H2 shard {idx+1}/{SHARD_COUNT} symbols={j}/{len(selected)} cases={len(report['cases'])} controls={len(report['controls'])} api_requests={report['requests']}",flush=True)
    p=Path(out);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    failed=sum("error" in x for x in report["symbol_audit"])
    print(json.dumps({"shard":idx,"symbols":len(selected),"case_results":len(report["cases"]),
                      "control_results":len(report["controls"]),"errors":failed,"requests":report["requests"]}))
    # Preserve reports for every failure; signal scientifically invalid if >20% fetch failure.
    return 0 if failed<=max(3,int(0.20*len(selected))) else 2

if __name__=="__main__":sys.exit(run())
