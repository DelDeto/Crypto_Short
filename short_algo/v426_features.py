"""V4.2.6 features: dense market context + executable 2R reference geometry."""

from .v425_features import build_v425_features
from .v426_config import (
    V426_MIN_SUPPORT_ROOM_R,
    V426_STOP_BUFFER_ATR,
    V426_ZONE_NEAR_ATR,
)


STRONG_ZONE_SOURCES = {
    "SUPPLY_1H",
    "SUPPLY_4H",
    "BROKEN_SUPPORT_RETEST",
    "SWEEP_RETEST",
}


def build_v426_features(base, one, four, btc_one, eth_one):
    row = build_v425_features(base, one, four, btc_one, eth_one)
    if row is None:
        return None

    current = float(row["current_price"])
    a1 = float(row["atr_1h"])
    lower = row.get("preferred_zone_lower")
    upper = row.get("preferred_zone_upper")
    source = str(row.get("zone_source") or "NO_ZONE")

    if lower is None or upper is None:
        row.update({
            "v426_entry_reference": None,
            "v426_stop_reference": None,
            "v426_tp2r_reference": None,
            "v426_risk": None,
            "v426_entry_zone_distance_atr": None,
            "v426_support_room_r": None,
            "v426_rr2_room_ok": 0,
            "v426_strong_zone": 0,
            "v426_near_zone": 0,
        })
        return row

    lower = float(lower)
    upper = float(upper)

    if lower <= current <= upper:
        entry = current
        distance = 0.0
    elif current < lower:
        entry = lower
        distance = (lower - current) / max(a1, 1e-12)
    else:
        entry = current
        distance = (current - upper) / max(a1, 1e-12)

    stop = max(upper, entry) + float(V426_STOP_BUFFER_ATR) * a1
    risk = stop - entry

    support_distance = row.get("support_distance_atr")
    support_room_r = None
    rr2_room_ok = 0
    if (
        risk > 0
        and support_distance is not None
    ):
        support_price = (
            current - float(support_distance) * a1
        )
        support_room_r = (entry - support_price) / risk
        rr2_room_ok = int(
            support_room_r >= float(V426_MIN_SUPPORT_ROOM_R)
        )

    row.update({
        "v426_entry_reference": entry,
        "v426_stop_reference": stop if risk > 0 else None,
        "v426_tp2r_reference": (
            entry - 2.0 * risk if risk > 0 else None
        ),
        "v426_risk": risk if risk > 0 else None,
        "v426_entry_zone_distance_atr": round(distance, 4),
        "v426_support_room_r": (
            None if support_room_r is None
            else round(float(support_room_r), 4)
        ),
        "v426_rr2_room_ok": rr2_room_ok,
        "v426_strong_zone": int(source in STRONG_ZONE_SOURCES),
        "v426_near_zone": int(
            distance <= float(V426_ZONE_NEAR_ATR)
        ),
    })
    return row
