"""Read-only MEXC futures market data; no orders or credentials.

MEXC moved futures endpoints to api.mexc.com in Jan 2026.
Kline fetches are segmented below its documented 2,000-bar request limit.
"""
import random,time
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import requests
from .config import API_BASE,MAX_KLINE_BARS_PER_REQUEST,INTERVAL_SECONDS

_SESSION=requests.Session()

def _get(path,params=None):
    last=None
    for attempt in range(5):
        try:
            r=_SESSION.get(API_BASE+path,params=params,timeout=25)
            if r.status_code in (429,500,502,503,504):
                raise requests.RequestException(f"HTTP {r.status_code}")
            r.raise_for_status()
            p=r.json()
            if not isinstance(p,dict) or p.get("success") is False or p.get("code") not in (None,0):
                raise RuntimeError(f"MEXC API payload error at {path}: {str(p)[:400]}")
            return p.get("data")
        except (requests.RequestException,ValueError) as exc:
            last=exc
            if attempt==4:break
            time.sleep(min(2**attempt,12)+random.random()*0.1)
    raise RuntimeError(f"MEXC GET {path} failed: {last}")

def snapshot_universe():
    from short_algo.mexc import _is_crypto_contract
    data=_get("/api/v1/contract/detail")
    if not isinstance(data,list):raise RuntimeError("Unexpected contract catalogue schema")
    symbols=[];rejections={"non_usdt":0,"inactive":0,"non_crypto":0,"non_perpetual":0,"malformed":0}
    for row in data:
        if not isinstance(row,dict) or not row.get("symbol"):
            rejections["malformed"]+=1;continue
        s=str(row["symbol"])
        if (row.get("quoteCoin") or row.get("settleCoin"))!="USDT":
            rejections["non_usdt"]+=1;continue
        if row.get("state") in (2,3,4,"2","3","4"):
            rejections["inactive"]+=1;continue
        if row.get("futureType") is not None and str(row["futureType"])!="1":
            rejections["non_perpetual"]+=1;continue
        if not _is_crypto_contract(s):
            rejections["non_crypto"]+=1;continue
        symbols.append(s)
    return sorted(set(symbols)),{"catalogue_rows":len(data),"excluded":rejections}

def _candle_frame(payload):
    if not isinstance(payload,dict):raise RuntimeError("Malformed MEXC OHLCV payload")
    fields=("time","open","high","low","close")
    arrays=[payload.get(k) or [] for k in fields]
    n=len(arrays[0])
    if not n or any(len(a)!=n for a in arrays):
        return pd.DataFrame(columns=["open","high","low","close","volume","amount"])
    vol=payload.get("vol") or payload.get("volume") or [np.nan]*n
    amount=payload.get("amount") or [np.nan]*n
    if len(vol)!=n or len(amount)!=n:raise RuntimeError("MEXC candle schema array length mismatch")
    df=pd.DataFrame({"time":arrays[0],"open":arrays[1],"high":arrays[2],"low":arrays[3],"close":arrays[4],"volume":vol,"amount":amount})
    seconds=pd.to_numeric(df["time"],errors="coerce")
    seconds=np.where(seconds>10**11,seconds/1000,seconds)
    df["time"]=pd.to_datetime(seconds,unit="s",utc=True,errors="coerce")
    for c in ("open","high","low","close","volume","amount"):
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=["time","open","high","low","close"])
    df=df.loc[(df["open"]>0)&(df["high"]>0)&(df["low"]>0)&(df["close"]>0)]
    if ((df["low"]>df["high"]) | (df["open"]>df["high"]) | (df["close"]>df["high"]) | (df["open"]<df["low"]) | (df["close"]<df["low"])).any():
        raise RuntimeError("Invalid OHLC ordering")
    if df.empty:return pd.DataFrame(columns=["open","high","low","close","volume","amount"])
    return df.drop_duplicates("time").sort_values("time").set_index("time")[["open","high","low","close","volume","amount"]]

def fetch_hourly(symbol,start,end):
    start=pd.Timestamp(start);end=pd.Timestamp(end)
    start=start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end=end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    if end<start:raise ValueError("Invalid window")
    begin=int(start.timestamp());finish=int(end.timestamp())
    chunk=max(1,min(int(MAX_KLINE_BARS_PER_REQUEST),1800))
    frames=[];queries=0
    while begin<=finish:
        # Inclusive endpoints: <= chunk bars, never silently truncate at 2000.
        stop=min(finish,begin+(chunk-1)*INTERVAL_SECONDS)
        data=_get(f"/api/v1/contract/kline/{symbol}",{
            "interval":"Min60","start":begin,"end":stop,
        })
        queries+=1
        f=_candle_frame(data)
        if not f.empty:frames.append(f)
        begin=stop+INTERVAL_SECONDS
        time.sleep(0.12)
    if not frames:
        return pd.DataFrame(columns=["open","high","low","close","volume","amount"]),queries
    out=pd.concat(frames).sort_index()
    out=out.loc[~out.index.duplicated(keep="last")]
    return out.loc[(out.index>=start)&(out.index<=end)],queries

def coverage(frame,start,end):
    if frame is None or frame.empty:return 0.0
    expected=max(1,int((pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()//3600)+1)
    present=len(frame.loc[(frame.index>=pd.Timestamp(start))&(frame.index<=pd.Timestamp(end))])
    return round(min(present/expected,1.0),5)
