"""M3 V3.6 — frozen Candidate B + regime/relative-weakness diagnostics.

Research only. Candidate B and Entry B remain frozen. This module only adds
causal context features for stratified analysis.
"""
import pandas as pd

from .indicators import atr, ema, return_pct, volume_ratio
from .m3_v21_execution import evaluate_m3_v21
from .m3_v2_execution import _find_displacement_retest, _three_pct_outcome
from .m3_v36_config import M3_V36_LIMIT_FILL_BARS, M3_V36_MAX_TARGET_ATR, M3_V36_MIN_QUALITY


def _poi_limit_entry(fifteen, seq):
    if seq.get("state")!="RETEST_ENTRY":
        return {"state":"NO_ENTRY"}
    frame=fifteen.sort_index()
    first_i=int(seq["entry_idx"])
    poi=float(seq["break_level"])
    last_i=min(len(frame)-1, first_i+int(M3_V36_LIMIT_FILL_BARS)-1)
    for i in range(first_i,last_i+1):
        if float(frame.iloc[i]["high"])>=poi:
            return {"state":"FILLED","entry":poi,"entry_idx":i,"entry_time":frame.index[i],"wait_bars":i-first_i}
    return {"state":"NO_FILL"}


def _context_features(one_closed, btc_closed, eth_closed, poi):
    close=one_closed["close"].astype(float)
    a1=float(atr(one_closed,14).iloc[-1])
    a1=max(a1,1e-12)
    px=float(close.iloc[-1])
    e20=float(ema(close,20).iloc[-1])
    e50=float(ema(close,50).iloc[-1])

    coin4=return_pct(close,4)
    coin24=return_pct(close,24)

    def market_ret(frame,bars):
        if frame is None or frame.empty or len(frame)<=bars:
            return 0.0
        return return_pct(frame["close"],bars)

    btc4,eth4=market_ret(btc_closed,4),market_ret(eth_closed,4)
    btc24,eth24=market_ret(btc_closed,24),market_ret(eth_closed,24)
    market4=(btc4+eth4)/2.0
    market24=(btc24+eth24)/2.0

    market_state="RISK_ON_STRONG" if market4>=1 and market24>=2 else ("RISK_OFF" if market4<=-0.8 and market24<=0 else "NEUTRAL")
    breakdown=max(0.0,float(poi)-px)/a1

    return {
        "m3v36_coin_return_4h_pct":round(coin4,5),
        "m3v36_coin_return_24h_pct":round(coin24,5),
        "m3v36_market_return_4h_pct":round(market4,5),
        "m3v36_market_return_24h_pct":round(market24,5),
        "m3v36_relative_weakness_4h_pct":round(coin4-market4,5),
        "m3v36_relative_weakness_24h_pct":round(coin24-market24,5),
        "m3v36_market_state":market_state,
        "m3v36_distance_to_ema20_atr1h":round((px-e20)/a1,5),
        "m3v36_distance_to_ema50_atr1h":round((px-e50)/a1,5),
        "m3v36_breakdown_strength_atr1h":round(breakdown,5),
        "m3v36_volume_expansion_1h":round(volume_ratio(one_closed,20),5),
    }


def evaluate_m3_v36(one_closed, four_closed, fifteen, signal_time, btc_closed=None, eth_closed=None):
    out=evaluate_m3_v21(one_closed,four_closed,fifteen,signal_time)
    if out.get("m3v21_state")!="ENTRY_BENCHMARK":
        out["m3v36_state"]="NO_BASE_ENTRY"
        return out

    quality=int(out.get("m3v21_retest_quality_score") or 0)
    target_atr=float(out.get("m3v2_target3_atr") or 99.0)
    core=bool(
        out.get("m3v2_poi_source")=="BROKEN_SUPPORT_1H"
        and quality>=int(M3_V36_MIN_QUALITY)
        and target_atr<=float(M3_V36_MAX_TARGET_ATR)
    )
    if not core:
        out["m3v36_state"]="FAIL_FROZEN_BASELINE"
        return out

    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v36_state"]="NO_RETEST"
        return out

    out.update(_context_features(one_closed,btc_closed,eth_closed,seq["break_level"]))

    entry=_poi_limit_entry(fifteen,seq)
    out["m3v36_state"]="BASELINE_CANDIDATE"
    out["m3v36_entry_state"]=entry.get("state")
    out["m3v36_poi"]=round(float(seq["break_level"]),10)
    if entry.get("state")!="FILLED":
        return out

    price=float(entry["entry"])
    idx=int(entry["entry_idx"])
    out.update({
        "m3v36_entry":round(price,10),
        "m3v36_entry_time":pd.Timestamp(entry["entry_time"]).isoformat(),
        "m3v36_entry_wait_bars":int(entry["wait_bars"]),
    })
    for key,value in _three_pct_outcome(fifteen,idx,price).items():
        out[key.replace("m3v2_","m3v36_")]=value
    return out
