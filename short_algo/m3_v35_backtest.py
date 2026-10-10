"""M3 V3.5 temporal OOS sharded replay."""
import json, os
import pandas as pd

from .config import BACKTEST_SHARD_COUNT,BACKTEST_SHARD_INDEX,BACKTEST_WARMUP_DAYS
from .m3_v35_config import M3_V35_COOLDOWN_HOURS
from .m3_v35_execution import evaluate_m3_v35
from .mexc import fetch_backtest_frames


def _load_manifest(path=None):
    path=path or os.getenv("M3_V35_MANIFEST_PATH","frozen/m3_v35_manifest.json")
    with open(path,encoding="utf-8") as f:
        return json.load(f)


def _apply_shard(symbols):
    return [s for i,s in enumerate(symbols) if i%int(BACKTEST_SHARD_COUNT)==int(BACKTEST_SHARD_INDEX)]


def _closed(frame,t,hours):
    if frame is None or frame.empty:
        return None
    return frame.loc[(frame.index+pd.Timedelta(hours=hours))<=pd.Timestamp(t)]


def _replay(symbol,frames,start,end):
    f15,one,four=frames.get("15M"),frames.get("1H"),frames.get("4H")
    if any(x is None or x.empty for x in (f15,one,four)):
        return [],{"symbol":symbol,"error":"missing frames"}
    f15,one,four=f15.sort_index(),one.sort_index(),four.sort_index()
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if start.tzinfo is None: start=start.tz_localize("UTC")
    if end.tzinfo is None: end=end.tz_localize("UTC")

    rows=[]; last=None
    for pos,ts in enumerate(one.index):
        signal_time=ts+pd.Timedelta(hours=1)
        if pos<100 or not(start<=signal_time<=end):
            continue
        four_closed=_closed(four,signal_time,4)
        if four_closed is None or len(four_closed)<60:
            continue
        row=evaluate_m3_v35(one.iloc[:pos+1],four_closed,f15,signal_time)
        if row.get("m3v35_state")!="FROZEN_CANDIDATE":
            continue
        if last is not None and signal_time-last<pd.Timedelta(hours=int(M3_V35_COOLDOWN_HOURS)):
            continue
        last=signal_time
        rows.append({"symbol":symbol,"signal_time":signal_time.isoformat(),**row})
    return rows,None


def run_m3_v35_backtest(path=None):
    manifest=_load_manifest(path)
    ps,pe,fe=map(pd.Timestamp,(manifest["period_start"],manifest["period_end"],manifest["future_end"]))
    selected=_apply_shard(manifest["symbols"])
    warm=ps-pd.Timedelta(days=int(BACKTEST_WARMUP_DAYS))

    rows=[]; errors=[]
    for idx,symbol in enumerate(selected,1):
        try:
            frames=fetch_backtest_frames(symbol,ps,fe,warmup_days=BACKTEST_WARMUP_DAYS)
            part,err=_replay(symbol,frames,ps,pe)
            rows+=part
            if err: errors.append(err)
        except Exception as exc:
            errors.append({"symbol":symbol,"error":str(exc)})
        print(f"[M3 V3.5 {int(BACKTEST_SHARD_INDEX)+1}/{int(BACKTEST_SHARD_COUNT)}] [{idx}/{len(selected)}] {symbol}: rows={len(rows)} errors={len(errors)}",flush=True)

    return {
        "engine":"M3 V3.5 Frozen Rule Temporal OOS",
        "manifest_id":manifest["manifest_id"],
        "manifest":manifest,
        "period_start":manifest["period_start"],
        "period_end":manifest["period_end"],
        "days":manifest["days"],
        "shard_index":int(BACKTEST_SHARD_INDEX),
        "shard_count":int(BACKTEST_SHARD_COUNT),
        "selected_symbols":selected,
        "selected_symbol_count":len(selected),
        "rows":rows,
        "errors":errors,
    }
