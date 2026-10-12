"""M4 V0.1 coverage audit + V0.2 H1 event extraction across ALL frozen symbols."""
import json,os,sys
import pandas as pd
from .config import SHARD_COUNT,SHARD_INDEX,OUT_DIR,MAX_ERROR_RATE
from .market import fetch_hourly,coverage
from .events import evaluate_frame

def main():
    path=os.getenv("M4_MANIFEST_PATH","frozen/m4/manifest.json")
    with open(path,encoding="utf-8") as f:m=json.load(f)
    if int(m["shard_count"])!=int(SHARD_COUNT):raise RuntimeError("Shard layout differs from frozen manifest")
    if not 0<=SHARD_INDEX<SHARD_COUNT:raise ValueError("Invalid shard index")
    selected=[s for n,s in enumerate(m["symbols"]) if n%SHARD_COUNT==SHARD_INDEX]
    report=[];events=[];control_pool=[];total_queries=0
    for n,s in enumerate(selected,1):
        entry={"symbol":s,"eligible":False}
        try:
            f,queries=fetch_hourly(s,m["fetch_start"],m["last_closed_candle_open"])
            total_queries+=queries
            entry["bars"]=len(f)
            entry["coverage"]=coverage(f,m["signal_start"],m["last_closed_candle_open"])
            entry["first_candle"]=f.index.min().isoformat() if len(f) else None
            entry["last_candle"]=f.index.max().isoformat() if len(f) else None
            if entry["coverage"]>=0.90:
                es,cs,audit=evaluate_frame(f,s,m["signal_start"],m["signal_end_exclusive"])
                entry["eligible"]=True
                entry["audit"]=audit
                events.extend(es);control_pool.extend(cs)
            else:
                entry["reason"]="INSUFFICIENT_60D_HISTORY_COVERAGE"
        except Exception as exc:
            entry["reason"]="FETCH_OR_PARSE_ERROR"
            entry["error"]=str(exc)[:500]
        report.append(entry)
        if n%25==0 or n==len(selected):
            print(f"M4 shard {SHARD_INDEX+1}/{SHARD_COUNT} symbols {n}/{len(selected)}, events={len(events)}, controls={len(control_pool)}, queries={total_queries}",flush=True)
    errors=sum(1 for r in report if r.get("reason")=="FETCH_OR_PARSE_ERROR")
    out={
        "manifest_id":m["manifest_id"],"shard_index":SHARD_INDEX,"shard_count":SHARD_COUNT,
        "selected_symbols":selected,"coverage_audit":report,
        "events":events,"control_pool":control_pool,
        "fetch_request_count":total_queries,"error_count":errors,
        "research_only":True,
    }
    os.makedirs(OUT_DIR,exist_ok=True)
    with open(os.path.join(OUT_DIR,"shard.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False)
    print(json.dumps({"shard":SHARD_INDEX,"symbols":len(selected),"eligible":sum(1 for r in report if r["eligible"]),"events":len(events),"control_points":len(control_pool),"errors":errors,"requests":total_queries}))
    if not selected or errors>max(3,MAX_ERROR_RATE*len(selected)):
        return 2
    return 0

if __name__=="__main__":sys.exit(main())
