"""V4.2.8 signal-time features: trend context + confirmed zone rejection."""

from .v425_features import build_v425_features
from .v428_config import (
    V428_CONFIRM_MAX_BELOW_ZONE_ATR,
    V428_MIN_CONFIRM_SCORE,
    V428_MIN_SUPPORT_ROOM_R,
    V428_RECLAIM_BUFFER_ATR,
    V428_REJECTION_CLOSE_POSITION,
    V428_REJECTION_UPPER_WICK_RATIO,
    V428_STOP_BUFFER_ATR,
    V428_TOUCH_LOOKBACK_1H,
    V428_TOUCH_TOLERANCE_ATR,
)


STRONG_ZONE_SOURCES = {
    "SUPPLY_1H",
    "SUPPLY_4H",
    "BROKEN_SUPPORT_RETEST",
    "SWEEP_RETEST",
}


def _bar_metrics(row):
    o=float(row["open"])
    h=float(row["high"])
    l=float(row["low"])
    c=float(row["close"])
    rng=max(h-l,1e-12)
    return {
        "bearish":c<o,
        "upper_wick_ratio":(h-max(o,c))/rng,
        "close_position":(c-l)/rng,
        "high":h,
        "low":l,
        "close":c,
    }


def _entry_confirmation(one,lower,upper,current,a1,support_distance_atr):
    lookback=max(2,int(V428_TOUCH_LOOKBACK_1H))
    recent=one.tail(lookback)
    tolerance=float(V428_TOUCH_TOLERANCE_ATR)*a1
    touch_mask=(
        (recent["high"].astype(float)>=lower-tolerance)
        & (recent["low"].astype(float)<=upper+tolerance)
    )
    touch_positions=[
        i for i,value in enumerate(touch_mask.tolist()) if value
    ]
    touched=bool(touch_positions)
    touch_age=None
    post_touch=recent.iloc[0:0]
    if touched:
        last_touch_pos=touch_positions[-1]
        touch_age=len(recent)-1-last_touch_pos
        post_touch=recent.iloc[last_touch_pos:]

    reclaim=False
    if touched and not post_touch.empty:
        reclaim=bool(
            (
                post_touch["close"].astype(float)
                > upper+float(V428_RECLAIM_BUFFER_ATR)*a1
            ).any()
        )

    latest=_bar_metrics(one.iloc[-1])
    previous=_bar_metrics(one.iloc[-2])
    bearish_rejection=bool(
        latest["bearish"]
        and (
            latest["upper_wick_ratio"]
            >=float(V428_REJECTION_UPPER_WICK_RATIO)
            or latest["close_position"]
            <=float(V428_REJECTION_CLOSE_POSITION)
        )
    )
    micro_turn_down=bool(
        latest["close"]<previous["close"]
        and (
            latest["high"]<previous["high"]
            or latest["low"]<previous["low"]
        )
    )
    mid=(lower+upper)/2.0
    close_below_mid=bool(current<=mid)
    below_atr=max(0.0,(lower-current)/max(a1,1e-12))

    score=0
    score+=int(touched)
    score+=int(not reclaim and touched)
    score+=int(bearish_rejection)
    score+=int(micro_turn_down)
    score+=int(close_below_mid)

    confirmed=bool(
        touched
        and not reclaim
        and bearish_rejection
        and micro_turn_down
        and score>=int(V428_MIN_CONFIRM_SCORE)
        and below_atr<=float(V428_CONFIRM_MAX_BELOW_ZONE_ATR)
    )

    touch_high=None
    if touched and not post_touch.empty:
        touch_high=float(post_touch["high"].astype(float).max())

    confirm_entry=current
    stop=(
        max(upper,touch_high if touch_high is not None else upper)
        +float(V428_STOP_BUFFER_ATR)*a1
    )
    risk=stop-confirm_entry
    tp2r=confirm_entry-2.0*risk if risk>0 else None

    support_room_r=None
    if risk>0 and support_distance_atr is not None:
        support_price=current-float(support_distance_atr)*a1
        support_room_r=(confirm_entry-support_price)/risk

    return {
        "v428_zone_touched_recent":int(touched),
        "v428_zone_touch_age_1h":touch_age,
        "v428_reclaim_after_touch":int(reclaim),
        "v428_no_reclaim_after_touch":int(touched and not reclaim),
        "v428_bearish_rejection_now":int(bearish_rejection),
        "v428_rejection_upper_wick_ratio":round(latest["upper_wick_ratio"],4),
        "v428_rejection_close_position":round(latest["close_position"],4),
        "v428_micro_turn_down":int(micro_turn_down),
        "v428_close_below_zone_mid":int(close_below_mid),
        "v428_confirmation_below_zone_atr":round(below_atr,4),
        "v428_entry_confirm_score":score,
        "v428_entry_confirmed":int(confirmed),
        "v428_confirm_entry_reference":confirm_entry,
        "v428_confirm_stop_reference":stop if risk>0 else None,
        "v428_confirm_tp2r_reference":tp2r,
        "v428_confirm_risk":risk if risk>0 else None,
        "v428_confirm_support_room_r":(
            None if support_room_r is None
            else round(float(support_room_r),4)
        ),
        "v428_confirm_rr2_room_ok":int(
            support_room_r is not None
            and support_room_r>=float(V428_MIN_SUPPORT_ROOM_R)
        ),
    }


def build_v428_features(base,one,four,btc_one,eth_one):
    row=build_v425_features(base,one,four,btc_one,eth_one)
    if row is None:
        return None

    current=float(row["current_price"])
    a1=float(row["atr_1h"])
    lower=row.get("preferred_zone_lower")
    upper=row.get("preferred_zone_upper")
    source=str(row.get("zone_source") or "NO_ZONE")

    if lower is None or upper is None:
        row.update({
            "v428_entry_zone_distance_atr":None,
            "v428_strong_zone":0,
            "v428_near_zone":0,
            "v428_in_zone":0,
            "v428_below_zone":0,
            "v428_zone_touched_recent":0,
            "v428_zone_touch_age_1h":None,
            "v428_reclaim_after_touch":0,
            "v428_no_reclaim_after_touch":0,
            "v428_bearish_rejection_now":0,
            "v428_rejection_upper_wick_ratio":None,
            "v428_rejection_close_position":None,
            "v428_micro_turn_down":0,
            "v428_close_below_zone_mid":0,
            "v428_confirmation_below_zone_atr":None,
            "v428_entry_confirm_score":0,
            "v428_entry_confirmed":0,
            "v428_confirm_entry_reference":None,
            "v428_confirm_stop_reference":None,
            "v428_confirm_tp2r_reference":None,
            "v428_confirm_risk":None,
            "v428_confirm_support_room_r":None,
            "v428_confirm_rr2_room_ok":0,
        })
        return row

    lower=float(lower)
    upper=float(upper)
    if lower<=current<=upper:
        distance=0.0
    elif current<lower:
        distance=(lower-current)/max(a1,1e-12)
    else:
        distance=(current-upper)/max(a1,1e-12)

    row.update({
        "v428_entry_zone_distance_atr":round(distance,4),
        "v428_strong_zone":int(source in STRONG_ZONE_SOURCES),
        "v428_near_zone":int(distance<=0.75),
        "v428_in_zone":int(lower<=current<=upper),
        "v428_below_zone":int(current<lower),
    })
    row.update(_entry_confirmation(
        one,lower,upper,current,a1,row.get("support_distance_atr")
    ))
    return row
