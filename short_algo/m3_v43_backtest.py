"""M3 V4.3 sharded exit-architecture replay."""
import json,os,pandas as pd
from .config import BACKTEST_SHARD_COUNT,BACKTEST_SHARD_INDEX,BACKTEST_WARMUP_DAYS
from .m3_v43_config import M3_V43_COOLDOWN_HOURS
from .m3_v43_execution import evaluate_m3_v43
from .mexc import fetch_backtest_frames,get_klines_window

def _load(path=None):
    p=path or os.getenv("M3_V43_MANIFEST_PATH","frozen/m3_v43_manifest.json")
    with open(p,encoding="utf-8") as f:return json.load(f)
def _shard(xs):return [s for i,s in enumerate(xs) if i%int(BACKTEST_SHARD_COUNT)==int(BACKTEST_SHARD_INDEX)]
def _closed(df,t,h):
    if df is None or df.empty:return None
    return df.loc[(df.index+pd.Timedelta(hours=h))<=pd.Timestamp(t)]
def _bid(t,blocks):
    t=pd.Timestamp(t)
    for b in blocks:
        if pd.Timestamp(b["start"])<=t<pd.Timestamp(b["end"]):return int(b["block"])
    return None
def _replay(symbol,frames,start,end,blocks,btc,eth):
    f15,one,four=frames.get("15M"),frames.get("1H"),frames.get("4H")
    if any(x is None or x.empty for x in (f15,one,four)):return [],{"symbol":symbol,"error":"missing frames"}
    f15,one,four=f15.sort_index(),one.sort_index(),four.sort_index();start,end=pd.Timestamp(start),pd.Timestamp(end)
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
        row=evaluate_m3_v43(one.iloc[:pos+1],fourc,f15,st,_closed(btc,st,1),_closed(eth,st,1))
        if row.get("m3v43_exit_state")!="EXIT_STUDY":continue
        if last is not None and st-last<pd.Timedelta(hours=int(M3_V43_COOLDOWN_HOURS)):continue
        last=st;rows.append({"symbol":symbol,"signal_time":st.isoformat(),"m3v43_block":block,**row})
    return rows,None
def run_m3_v43_backtest(path=None):
    m=_load(path);ps,pe,fe=map(pd.Timestamp,(m["period_start"],m["period_end"],m["future_end"]));sel=_shard(m["symbols"]);warm=ps-pd.Timedelta(days=int(BACKTEST_WARMUP_DAYS));errors=[];ctx={}
    for s in ("BTC_USDT","ETH_USDT"):
        try:ctx[s]=get_klines_window(s,"1h",warm,fe)
        except Exception as e:ctx[s]=None;errors.append({"symbol":s,"error":f"context: {e}"})
    rows=[]
    for i,s in enumerate(sel,1):
        try:
            frames=fetch_backtest_frames(s,ps,fe,warmup_days=BACKTEST_WARMUP_DAYS);part,err=_replay(s,frames,ps,pe,m["blocks"],ctx.get("BTC_USDT"),ctx.get("ETH_USDT"));rows+=part
            if err:errors.append(err)
        except Exception as e:errors.append({"symbol":s,"error":str(e)})
        print(f"[M3 V4.3 {int(BACKTEST_SHARD_INDEX)+1}/{int(BACKTEST_SHARD_COUNT)}] [{i}/{len(sel)}] {s}: rows={len(rows)} errors={len(errors)}",flush=True)
    return {"engine":"M3 V4.3 Exit Architecture","manifest_id":m["manifest_id"],"manifest":m,"period_start":m["period_start"],"period_end":m["period_end"],"block_days":m["block_days"],"block_count":m["block_count"],"shard_index":int(BACKTEST_SHARD_INDEX),"shard_count":int(BACKTEST_SHARD_COUNT),"selected_symbols":sel,"selected_symbol_count":len(sel),"rows":rows,"errors":errors}
