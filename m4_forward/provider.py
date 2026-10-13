"""M4-only MEXC client: shared global pacing, transient-error backoff and safe 1h candles.

The frozen H3 price/feature hypothesis is NEVER modified. This is a
collection-transport repair. No credentials, orders, or historical backfill.
"""
import random,threading,time
import requests
import pandas as pd
from m4_research.config import API_BASE
from m4_research.market import _candle_frame

# Operational throttle only, not a trading parameter or signal filter.
MIN_REQUEST_SPACING_SECONDS=0.80
MAX_RETRIES=7
HTTP_TIMEOUT_SECONDS=20
_H=pd.Timedelta(hours=1)
_lock=threading.Lock()
_next_allowed_at=0.0
_local=threading.local()

class RetryableMexcError(RuntimeError):pass

def _session():
    s=getattr(_local,"session",None)
    if s is None:
        s=requests.Session()
        _local.session=s
    return s

def _wait_turn():
    global _next_allowed_at
    with _lock:
        now=time.monotonic()
        wait=max(0.0,_next_allowed_at-now)
        _next_allowed_at=max(now,_next_allowed_at)+MIN_REQUEST_SPACING_SECONDS
    if wait:time.sleep(wait)

def _cooldown(seconds):
    global _next_allowed_at
    with _lock:
        _next_allowed_at=max(_next_allowed_at,time.monotonic()+max(0.0,seconds))

def _utc(ts):
    x=pd.Timestamp(ts)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")

def fetch_hourly_paced(symbol,start,end):
    """Same (DataFrame, count) interface as m4_research.market.fetch_hourly.

    One in-flight call per symbol, overall 0.80s global pacing. Returns the
    number of actual attempts, not simply the number of successful responses.
    """
    start=_utc(start);end=_utc(end)
    if end<start:raise ValueError("Bad M4 hourly history window")
    frames=[];attempts=0
    pos=start
    while pos<=end:
        until=min(end,pos+pd.Timedelta(hours=699))
        params={
            "interval":"Min60",
            "start":int(pos.timestamp()),
            "end":int(until.timestamp()),
        }
        result=None
        for attempt in range(MAX_RETRIES):
            _wait_turn()
            attempts+=1
            try:
                resp=_session().get(
                    API_BASE+f"/api/v1/contract/kline/{symbol}",
                    params=params,timeout=HTTP_TIMEOUT_SECONDS)
                if resp.status_code in (418,429,500,502,503,504):
                    raise RetryableMexcError(f"MEXC HTTP {resp.status_code}")
                resp.raise_for_status()
                payload=resp.json()
                if not isinstance(payload,dict):
                    raise RuntimeError("Malformed MEXC response")
                code=payload.get("code")
                msg=str(payload.get("message") or payload.get("msg") or "")
                # HTTP 200 + code=510 is MEXC's request-frequency rejection.
                if str(code)=="510" or "too frequent" in msg.lower():
                    raise RetryableMexcError(f"MEXC rate-limited 510: {msg[:160]}")
                if payload.get("success") is False or code not in (None,0,"0"):
                    raise RuntimeError(f"MEXC API code={code}: {msg[:160]}")
                result=_candle_frame(payload.get("data"))
                break
            except (requests.Timeout,requests.ConnectionError,RetryableMexcError) as exc:
                if attempt==MAX_RETRIES-1:
                    raise RuntimeError(f"MEXC transient error after {MAX_RETRIES} retries for {symbol}: {exc}") from exc
                # Global cooldown prevents five parallel threads from retry-storming.
                delay=min(3*(2**attempt),45)+random.random()*0.2
                _cooldown(delay)
            except (requests.RequestException,ValueError) as exc:
                raise RuntimeError(f"MEXC non-retryable API response for {symbol}: {exc}") from exc
        if result is None:raise RuntimeError("MEXC returned no candles (unexpected)")
        if not result.empty:frames.append(result)
        pos=until+_H
    if not frames:
        return pd.DataFrame(columns=["open","high","low","close","volume","amount"]),attempts
    frame=pd.concat(frames).sort_index()
    frame=frame.loc[~frame.index.duplicated(keep="last")]
    return frame.loc[(frame.index>=start)&(frame.index<=end)],attempts
