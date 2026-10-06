"""V4.2.7 feature extraction.

Trend features are inherited from the dense V4.2.5 market snapshot.
Entry geometry is calculated separately and is never included in the trend
feature list used by V4.2.7 trend models.
"""

from .v425_features import build_v425_features
from .v427_config import V427_MIN_SUPPORT_ROOM_R


STRONG_ZONE_SOURCES = {
    "SUPPLY_1H",
    "SUPPLY_4H",
    "BROKEN_SUPPORT_RETEST",
    "SWEEP_RETEST",
}


def build_v427_features(base, one, four, btc_one, eth_one):
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
            "v427_entry_reference":None,
            "v427_stop_reference":None,
            "v427_tp2r_reference":None,
            "v427_risk":None,
            "v427_entry_zone_distance_atr":None,
            "v427_support_room_r":None,
            "v427_rr2_room_ok":0,
            "v427_strong_zone":0,
            "v427_near_zone":0,
            "v427_in_zone":0,
            "v427_below_zone":0,
        })
        return row

    lower=float(lower)
    upper=float(upper)

    if lower<=current<=upper:
        entry=current
        distance=0.0
    elif current<lower:
        entry=lower
        distance=(lower-current)/max(a1,1e-12)
    else:
        entry=current
        distance=(current-upper)/max(a1,1e-12)

    # Keep the same stop geometry as V4.2.6 so the entry layer can be
    # compared directly; the 2R room requirement is slightly stricter.
    stop=max(upper,entry)+0.18*a1
    risk=stop-entry

    support_distance=row.get("support_distance_atr")
    support_room_r=None
    rr2_room_ok=0
    if risk>0 and support_distance is not None:
        support_price=current-float(support_distance)*a1
        support_room_r=(entry-support_price)/risk
        rr2_room_ok=int(
            support_room_r>=float(V427_MIN_SUPPORT_ROOM_R)
        )

    row.update({
        "v427_entry_reference":entry,
        "v427_stop_reference":stop if risk>0 else None,
        "v427_tp2r_reference":entry-2.0*risk if risk>0 else None,
        "v427_risk":risk if risk>0 else None,
        "v427_entry_zone_distance_atr":round(distance,4),
        "v427_support_room_r":(
            None if support_room_r is None
            else round(float(support_room_r),4)
        ),
        "v427_rr2_room_ok":rr2_room_ok,
        "v427_strong_zone":int(source in STRONG_ZONE_SOURCES),
        "v427_near_zone":int(distance<=0.75),
        "v427_in_zone":int(lower<=current<=upper),
        "v427_below_zone":int(current<lower),
    })
    return row
