"""M3 V2.1 — refined retest quality + structural demand diagnostics."""
import pandas as pd
from .indicators import atr, swing_points
from .m3_v2_execution import evaluate_m3_v2, _find_displacement_retest

STEP=pd.Timedelta(minutes=15)


def _structural_demand(one_closed, entry, atr1):
    """Find a meaningful confirmed 1H demand below entry.

    A swing low qualifies only if price subsequently bounced at least the
    configured ATR amount. This avoids treating every tiny nearby swing low
    as demand.
    """
    from .m3_v21_config import M3_V21_MIN_DEMAND_BOUNCE_ATR, M3_V21_MIN_DEMAND_DISTANCE_ATR
    _, lows=swing_points(one_closed,left=2,right=2)
    if not lows:
        return None
    a=max(float(atr1),1e-12)
    candidates=[]
    for low in lows:
        pos=int(low["pos"]); price=float(low["price"])
        if price>=float(entry):
            continue
        distance=(float(entry)-price)/a
        if distance<float(M3_V21_MIN_DEMAND_DISTANCE_ATR):
            continue
        after=one_closed.iloc[pos+1:min(pos+7,len(one_closed))]
        if after.empty:
            continue
        bounce=(float(after["high"].astype(float).max())-price)/a
        if bounce<float(M3_V21_MIN_DEMAND_BOUNCE_ATR):
            continue
        # Count nearby confirmed lows as support touches.
        touches=sum(abs(float(x["price"])-price)/a<=0.35 for x in lows)
        score=bounce+0.25*min(touches,4)
        candidates.append({"price":price,"bounce_atr":bounce,"touches":touches,"score":score,"time":low["time"]})
    if not candidates:
        return None
    # Prefer nearest significant demand; score is retained for diagnostics.
    candidates.sort(key=lambda x:(-x["price"],-x["score"]))
    return candidates[0]


def _retest_quality(fifteen, seq):
    """Score the failed retest using only candles known before entry."""
    if seq.get("state")!="RETEST_ENTRY":
        return {}
    entry_time=pd.Timestamp(seq["entry_time"])
    frame=fifteen.sort_index()
    if entry_time not in frame.index:
        return {}
    entry_i=frame.index.get_loc(entry_time)
    retest_i=entry_i-1
    # Find displacement bar by close time.
    disp_close=pd.Timestamp(seq["displacement_time"])
    disp_candidates=[i for i,t in enumerate(frame.index[:entry_i]) if t+STEP==disp_close]
    if not disp_candidates or retest_i<1:
        return {}
    disp_i=disp_candidates[-1]
    d=frame.iloc[disp_i]; r=frame.iloc[retest_i]
    a15_series=atr(frame,14)
    a=float(a15_series.iloc[retest_i]) if pd.notna(a15_series.iloc[retest_i]) else float(seq.get("atr15") or 0)
    a=max(a,1e-12)
    break_level=float(seq["break_level"])
    ro,rh,rl,rc=(float(r[k]) for k in ("open","high","low","close"))
    do,dh,dl,dc=(float(d[k]) for k in ("open","high","low","close"))
    penetration=max(0.0,rh-break_level)/a
    close_below=max(0.0,break_level-rc)/a
    rng=max(rh-rl,1e-12)
    upper_wick=rh-max(ro,rc)
    upper_wick_ratio=upper_wick/rng
    prior=frame.iloc[max(0,disp_i-4):disp_i]
    prior_high=float(prior["high"].astype(float).max()) if not prior.empty else rh
    lower_high=int(rh<prior_high)
    disp_vol=float(d.get("volume",0) or 0)
    retest_vol=float(r.get("volume",0) or 0)
    volume_ratio=retest_vol/max(disp_vol,1e-12) if disp_vol>0 else None
    score=0
    score+=int(float(seq.get("displacement_body_atr15") or 0)>=0.70)
    score+=int(penetration<=0.25)
    score+=int(close_below>=0.05)
    score+=int(upper_wick_ratio>=0.25)
    score+=int(lower_high==1)
    if volume_ratio is not None:
        score+=int(volume_ratio<=1.0)
    return {
        "m3v21_retest_quality_score":score,
        "m3v21_retest_penetration_atr15":round(penetration,5),
        "m3v21_retest_close_below_break_atr15":round(close_below,5),
        "m3v21_retest_upper_wick_ratio":round(upper_wick_ratio,5),
        "m3v21_retest_lower_high":lower_high,
        "m3v21_retest_volume_vs_displacement":round(volume_ratio,5) if volume_ratio is not None else None,
    }


def evaluate_m3_v21(one_closed,four_closed,fifteen,signal_time):
    base=evaluate_m3_v2(one_closed,four_closed,fifteen,signal_time)
    out=dict(base)
    # Keep only true V2 benchmark entries for V2.1 diagnostics.
    if base.get("m3v2_state")!="ENTRY_BENCHMARK":
        out["m3v21_state"]="NO_BASE_ENTRY"
        return out

    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v21_state"]="NO_RETEST_ENTRY"
        return out

    out.update(_retest_quality(fifteen,seq))
    entry=float(base["m3v2_entry"])
    atr1=float(base["m3v2_atr1h"])
    demand=_structural_demand(one_closed,entry,atr1)
    if demand:
        room=(entry-float(demand["price"]))/entry*100.0
        out.update({
            "m3v21_structural_demand":round(float(demand["price"]),10),
            "m3v21_structural_demand_room_pct":round(room,5),
            "m3v21_demand_bounce_atr":round(float(demand["bounce_atr"]),5),
            "m3v21_demand_touches":int(demand["touches"]),
            "m3v21_demand_score":round(float(demand["score"]),5),
        })
    else:
        room=None
        out.update({
            "m3v21_structural_demand":None,
            "m3v21_structural_demand_room_pct":None,
            "m3v21_demand_bounce_atr":None,
            "m3v21_demand_touches":None,
            "m3v21_demand_score":None,
        })

    from .m3_v21_config import (
        M3_V21_MAX_RETEST_PENETRATION_ATR,
        M3_V21_MAX_RETEST_VOLUME_RATIO,
        M3_V21_MAX_TARGET_ATR,
        M3_V21_MIN_RETEST_QUALITY,
        M3_V21_ROOM_GATE_PCT,
    )
    quality=int(out.get("m3v21_retest_quality_score") or 0)
    penetration=float(out.get("m3v21_retest_penetration_atr15") or 99)
    vol_ratio=out.get("m3v21_retest_volume_vs_displacement")
    target_atr=float(base.get("m3v2_target3_atr") or 99)
    out.update({
        "m3v21_quality_gate_pass":int(
            quality>=int(M3_V21_MIN_RETEST_QUALITY)
            and penetration<=float(M3_V21_MAX_RETEST_PENETRATION_ATR)
            and (vol_ratio is None or float(vol_ratio)<=float(M3_V21_MAX_RETEST_VOLUME_RATIO))
        ),
        "m3v21_room_gate_pass":int(room is not None and room>=float(M3_V21_ROOM_GATE_PCT)),
        "m3v21_vol_gate_pass":int(target_atr<=float(M3_V21_MAX_TARGET_ATR)),
        "m3v21_state":"ENTRY_BENCHMARK",
    })
    return out
