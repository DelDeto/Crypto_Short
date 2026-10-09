"""M3 V2.1 replay, preserving the V2 setup while refining entry quality."""
import json,os
import pandas as pd
from .config import BACKTEST_SHARD_COUNT,BACKTEST_SHARD_INDEX,BACKTEST_WARMUP_DAYS
from .indicators import return_pct
from .m3_v21_config import M3_V21_COOLDOWN_HOURS
from .m3_v21_execution import evaluate_m3_v21
from .mexc import fetch_backtest_frames,get_klines_window

def _load_manifest(path=None):
    path=path or os.getenv("M3_V21_MANIFEST_PATH","frozen/m3_v21_manifest.json")
    with open(path,encoding="utf-8") as f:return json.load(f)
def _apply_shard(symbols):return [s for i,s in enumerate(symbols) if i%int(BACKTEST_SHARD_COUNT)==int(BACKTEST_SHARD_INDEX)]
def _closed(frame,t,h):
    if frame is None or frame.empty:return None
    return frame.loc[(frame.index+pd.Timedelta(hours=h))<=pd.Timestamp(t)]
def _market(btc,eth,t):
    b=_closed(btc,t,1);e=_closed(eth,t,1)
    if b is None or e is None or len(b)<30 or len(e)<30:return {"m3v21_market_state":"UNKNOWN"}
    r4=(return_pct(b["close"],4)+return_pct(e["close"],4))/2;r24=(return_pct(b["close"],24)+return_pct(e["close"],24))/2
    st="RISK_ON_STRONG" if r4>=1 and r24>=2 else ("RISK_OFF" if r4<=-.8 and r24<=0 else "NEUTRAL")
    return {"m3v21_market_state":st,"m3v21_market_r4_pct":round(r4,4),"m3v21_market_r24_pct":round(r24,4)}
def _replay(symbol,frames,start,end,btc,eth):
    f15,one,four=frames.get("15M"),frames.get("1H"),frames.get("4H")
    if any(x is None or x.empty for x in (f15,one,four)):return [],{"symbol":symbol,"error":"missing frames"}
    f15,one,four=f15.sort_index(),one.sort_index(),four.sort_index()
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if start.tzinfo is None:start=start.tz_localize("UTC")
    if end.tzinfo is None:end=end.tz_localize("UTC")
    rows=[];last=None
    for pos,ts in enumerate(one.index):
        sig=ts+pd.Timedelta(hours=1)
        if pos<100 or not(start<=sig<=end):continue
        fc=_closed(four,sig,4)
        if fc is None or len(fc)<60:continue
        r=evaluate_m3_v21(one.iloc[:pos+1],fc,f15,sig)
        if r.get("m3v21_state")!="ENTRY_BENCHMARK":continue
        if last is not None and sig-last<pd.Timedelta(hours=int(M3_V21_COOLDOWN_HOURS)):continue
        last=sig
        rows.append({"symbol":symbol,"signal_time":sig.isoformat(),**_market(btc,eth,sig),**r})
    return rows,None
def run_m3_v21_backtest(path=None):
    m=_load_manifest(path);ps,pe,fe=map(pd.Timestamp,(m["period_start"],m["period_end"],m["future_end"]))
    selected=_apply_shard(m["symbols"]);warm=ps-pd.Timedelta(days=int(BACKTEST_WARMUP_DAYS))
    errors=[];ctx={}
    for s in ("BTC_USDT","ETH_USDT"):
        try:ctx[s]=get_klines_window(s,"1h",warm,fe)
        except Exception as exc:ctx[s]=None;errors.append({"symbol":s,"error":f"context: {exc}"})
    rows=[]
    for idx,s in enumerate(selected,1):
        try:
            frames=fetch_backtest_frames(s,ps,fe,warmup_days=BACKTEST_WARMUP_DAYS)
            part,err=_replay(s,frames,ps,pe,ctx.get("BTC_USDT"),ctx.get("ETH_USDT"));rows+=part
            if err:errors.append(err)
        except Exception as exc:errors.append({"symbol":s,"error":str(exc)})
        print(f"[M3 V2.1 {int(BACKTEST_SHARD_INDEX)+1}/{int(BACKTEST_SHARD_COUNT)}] [{idx}/{len(selected)}] {s}: entries={len(rows)} errors={len(errors)}",flush=True)
    return {"engine":"M3 V2.1 Entry Refinement","manifest_id":m["manifest_id"],"manifest":m,"period_start":m["period_start"],"period_end":m["period_end"],"future_end":m["future_end"],"days":m["days"],"shard_index":int(BACKTEST_SHARD_INDEX),"shard_count":int(BACKTEST_SHARD_COUNT),"selected_symbols":selected,"selected_symbol_count":len(selected),"entries":rows,"errors":errors}
