"""M3 V4.4.1 context-data preflight.

Validates BTC/ETH 15m/1h/4h coverage before any sharded replay starts.
This guard is operational QA, not a trading filter.
"""
import json,os
import pandas as pd

from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_CONTEXT_COVERAGE
from .mexc import get_klines_window

INTERVAL_MINUTES={"15m":15,"1h":60,"4h":240}

def _expected(start,end,minutes):
    seconds=(pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()
    return max(1,int(seconds//(minutes*60)))

def _coverage(frame,start,end,minutes):
    if frame is None or frame.empty:
        return {"bars":0,"expected":_expected(start,end,minutes),"coverage":0.0,"first":None,"last":None}
    x=frame.loc[(frame.index>=pd.Timestamp(start))&(frame.index<pd.Timestamp(end))]
    exp=_expected(start,end,minutes)
    return {
        "bars":int(len(x)),
        "expected":int(exp),
        "coverage":round(min(1.0,len(x)/max(exp,1)),4),
        "first":x.index[0].isoformat() if len(x) else None,
        "last":x.index[-1].isoformat() if len(x) else None,
    }

def run_preflight(manifest_path=None):
    manifest_path=manifest_path or os.getenv("M3_V441_MANIFEST_PATH","output/m3_v441_manifest.json")
    with open(manifest_path,encoding="utf-8") as f:
        m=json.load(f)
    start,end=m["period_start"],m["period_end"]
    detail={}
    ok=True
    for symbol in ("BTC_USDT","ETH_USDT"):
        detail[symbol]={}
        for interval,minutes in INTERVAL_MINUTES.items():
            try:
                frame=get_klines_window(symbol,interval,start,end)
                stat=_coverage(frame,start,end,minutes)
            except Exception as exc:
                stat={"bars":0,"expected":_expected(start,end,minutes),"coverage":0.0,"first":None,"last":None,"error":str(exc)}
            detail[symbol][interval]=stat
            if float(stat.get("coverage") or 0.0)<float(M3_V441_MIN_CONTEXT_COVERAGE):
                ok=False
    return {
        "manifest_id":m["manifest_id"],
        "period_start":start,
        "period_end":end,
        "minimum_context_coverage":float(M3_V441_MIN_CONTEXT_COVERAGE),
        "data_valid":bool(ok),
        "context":detail,
    }

def main():
    out=run_preflight()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v441_preflight.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out["data_valid"]:
        print("M3 V4.4.1 PRECHECK FAILED: BTC/ETH historical coverage is insufficient.")
        return 2
    return 0

if __name__=="__main__":
    raise SystemExit(main())
