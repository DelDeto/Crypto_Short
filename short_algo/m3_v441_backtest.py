"""M3 V4.4.1 fixed-date OOS replay with per-symbol coverage telemetry."""
import json,os
import pandas as pd

from .config import BACKTEST_SHARD_COUNT,BACKTEST_SHARD_INDEX,BACKTEST_WARMUP_DAYS
from .m3_v441_config import M3_V441_COOLDOWN_HOURS,M3_V441_MIN_SYMBOL_COVERAGE
from .m3_v441_execution import evaluate_m3_v441
from .mexc import fetch_backtest_frames,get_klines_window

INTERVAL_MINUTES={"15M":15,"1H":60,"4H":240}

def _load(path=None):
    p=path or os.getenv("M3_V441_MANIFEST_PATH","frozen/m3_v441_manifest.json")
    with open(p,encoding="utf-8") as f:return json.load(f)

def _shard(xs):
    return [s for i,s in enumerate(xs) if i%int(BACKTEST_SHARD_COUNT)==int(BACKTEST_SHARD_INDEX)]

def _closed(df,t,h):
    if df is None or df.empty:return None
    return df.loc[(df.index+pd.Timedelta(hours=h))<=pd.Timestamp(t)]

def _bid(t,blocks):
    t=pd.Timestamp(t)
    for b in blocks:
        if pd.Timestamp(b["start"])<=t<pd.Timestamp(b["end"]):return int(b["block"])
    return None

def _expected(start,end,minutes):
    return max(1,int((pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()//(minutes*60)))

def _frame_stat(frame,start,end,minutes):
    exp=_expected(start,end,minutes)
    if frame is None or frame.empty:
        return {"bars":0,"expected":exp,"coverage":0.0,"first":None,"last":None}
    x=frame.loc[(frame.index>=pd.Timestamp(start))&(frame.index<pd.Timestamp(end))]
    return {
        "bars":int(len(x)),"expected":int(exp),
        "coverage":round(min(1.0,len(x)/max(exp,1)),4),
        "first":x.index[0].isoformat() if len(x) else None,
        "last":x.index[-1].isoformat() if len(x) else None,
    }

def _coverage(frames,start,end):
    stats={k:_frame_stat(frames.get(k),start,end,m) for k,m in INTERVAL_MINUTES.items()}
    minimum=min(float(v["coverage"]) for v in stats.values())
    return {
        "timeframes":stats,
        "minimum_coverage":round(minimum,4),
        "eligible":int(minimum>=float(M3_V441_MIN_SYMBOL_COVERAGE)),
    }

def _replay(symbol,frames,start,end,blocks,btc,eth):
    f15,one,four=frames.get("15M"),frames.get("1H"),frames.get("4H")
    if any(x is None or x.empty for x in (f15,one,four)):
        return []
    f15,one,four=f15.sort_index(),one.sort_index(),four.sort_index()
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if start.tzinfo is None:start=start.tz_localize("UTC")
    if end.tzinfo is None:end=end.tz_localize("UTC")
    rows=[];last=None
    for pos,ts in enumerate(one.index):
        st=ts+pd.Timedelta(hours=1)
        if pos<100 or not(start<=st<end):continue
        block=_bid(st,blocks)
        if block is None:continue
        fourc=_closed(four,st,4)
        if fourc is None or len(fourc)<60:continue
        row=evaluate_m3_v441(one.iloc[:pos+1],fourc,f15,st,_closed(btc,st,1),_closed(eth,st,1))
        if row.get("m3v441_exit_state")!="EXIT_STUDY":continue
        if last is not None and st-last<pd.Timedelta(hours=int(M3_V441_COOLDOWN_HOURS)):continue
        last=st
        rows.append({"symbol":symbol,"signal_time":st.isoformat(),"m3v441_block":block,**row})
    return rows

def run_m3_v441_backtest(path=None):
    m=_load(path)
    ps,pe,fe=map(pd.Timestamp,(m["period_start"],m["period_end"],m["future_end"]))
    selected=_shard(m["symbols"])
    warm=ps-pd.Timedelta(days=int(BACKTEST_WARMUP_DAYS))
    errors=[];coverage=[];ctx={}
    for s in ("BTC_USDT","ETH_USDT"):
        try:ctx[s]=get_klines_window(s,"1h",warm,fe)
        except Exception as exc:
            ctx[s]=None;errors.append({"symbol":s,"stage":"context_1h","error":str(exc)})

    rows=[]
    for i,s in enumerate(selected,1):
        try:
            frames=fetch_backtest_frames(s,ps,fe,warmup_days=BACKTEST_WARMUP_DAYS)
            stat=_coverage(frames,ps,pe)
            coverage.append({"symbol":s,**stat})
            if int(stat["eligible"])==1:
                rows+=_replay(s,frames,ps,pe,m["blocks"],ctx.get("BTC_USDT"),ctx.get("ETH_USDT"))
        except Exception as exc:
            coverage.append({"symbol":s,"timeframes":{},"minimum_coverage":0.0,"eligible":0,"error":str(exc)})
            errors.append({"symbol":s,"stage":"frames","error":str(exc)})
        print(f"[M3 V4.4.1 {int(BACKTEST_SHARD_INDEX)+1}/{int(BACKTEST_SHARD_COUNT)}] [{i}/{len(selected)}] {s}: rows={len(rows)} eligible={sum(int(x.get('eligible') or 0) for x in coverage)} errors={len(errors)}",flush=True)

    return {
        "engine":"M3 V4.4.1 Fixed OOS Data Guard",
        "manifest_id":m["manifest_id"],"manifest":m,
        "period_start":m["period_start"],"period_end":m["period_end"],
        "block_days":m["block_days"],"block_count":m["block_count"],
        "minimum_symbol_coverage":float(M3_V441_MIN_SYMBOL_COVERAGE),
        "shard_index":int(BACKTEST_SHARD_INDEX),"shard_count":int(BACKTEST_SHARD_COUNT),
        "selected_symbols":selected,"selected_symbol_count":len(selected),
        "eligible_symbol_count":sum(int(x.get("eligible") or 0) for x in coverage),
        "coverage":coverage,"rows":rows,"errors":errors,
    }
