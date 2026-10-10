"""M3 V3.5 — frozen V3.4 candidates on temporal OOS.

Execution is fixed to Entry B: sell-limit at broken-support POI for up to two
15m bars after the failed retest. No thresholds are tuned in this module.
"""
import pandas as pd

from .m3_v21_execution import evaluate_m3_v21
from .m3_v2_execution import _find_displacement_retest, _three_pct_outcome
from .m3_v35_config import (
    M3_V35_A_MAX_PENETRATION_ATR15,
    M3_V35_B_MIN_QUALITY,
    M3_V35_C_MAX_PENETRATION_ATR15,
    M3_V35_C_MAX_VOLUME_RATIO,
    M3_V35_C_MIN_UPPER_WICK_RATIO,
    M3_V35_C_REQUIRE_LOWER_HIGH,
    M3_V35_CORE_MAX_TARGET_ATR,
    M3_V35_CORE_MIN_QUALITY,
    M3_V35_LIMIT_FILL_BARS,
)


def _poi_limit_entry(fifteen,seq):
    if seq.get("state")!="RETEST_ENTRY":
        return {"state":"NO_ENTRY"}
    frame=fifteen.sort_index()
    first_i=int(seq["entry_idx"])
    poi=float(seq["break_level"])
    last_i=min(len(frame)-1,first_i+int(M3_V35_LIMIT_FILL_BARS)-1)
    for i in range(first_i,last_i+1):
        if float(frame.iloc[i]["high"])>=poi:
            return {"state":"FILLED","entry":poi,"entry_idx":i,"entry_time":frame.index[i],"wait_bars":i-first_i}
    return {"state":"NO_FILL"}


def evaluate_m3_v35(one_closed,four_closed,fifteen,signal_time):
    out=evaluate_m3_v21(one_closed,four_closed,fifteen,signal_time)
    if out.get("m3v21_state")!="ENTRY_BENCHMARK":
        out["m3v35_state"]="NO_BASE_ENTRY"
        return out

    quality=int(out.get("m3v21_retest_quality_score") or 0)
    target_atr=float(out.get("m3v2_target3_atr") or 99.0)
    core=bool(
        out.get("m3v2_poi_source")=="BROKEN_SUPPORT_1H"
        and quality>=int(M3_V35_CORE_MIN_QUALITY)
        and target_atr<=float(M3_V35_CORE_MAX_TARGET_ATR)
    )
    if not core:
        out["m3v35_state"]="FAIL_CORE"
        return out

    pen=float(out.get("m3v21_retest_penetration_atr15") or 99.0)
    wick=float(out.get("m3v21_retest_upper_wick_ratio") or 0.0)
    lower_high=int(out.get("m3v21_retest_lower_high") or 0)
    vol=out.get("m3v21_retest_volume_vs_displacement")
    vol_pass=(vol is None) or float(vol)<=float(M3_V35_C_MAX_VOLUME_RATIO)

    out["m3v35_candidate_a"]=int(pen<=float(M3_V35_A_MAX_PENETRATION_ATR15))
    out["m3v35_candidate_b"]=int(quality>=int(M3_V35_B_MIN_QUALITY))
    out["m3v35_candidate_c"]=int(
        pen<=float(M3_V35_C_MAX_PENETRATION_ATR15)
        and vol_pass
        and wick>=float(M3_V35_C_MIN_UPPER_WICK_RATIO)
        and lower_high==int(M3_V35_C_REQUIRE_LOWER_HIGH)
    )

    if not any(int(out.get(k) or 0) for k in ("m3v35_candidate_a","m3v35_candidate_b","m3v35_candidate_c")):
        out["m3v35_state"]="NO_FROZEN_CANDIDATE"
        return out

    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v35_state"]="NO_RETEST"
        return out

    entry=_poi_limit_entry(fifteen,seq)
    out["m3v35_state"]="FROZEN_CANDIDATE"
    out["m3v35_entry_state"]=entry.get("state")
    out["m3v35_poi"]=round(float(seq["break_level"]),10)
    if entry.get("state")!="FILLED":
        return out

    price=float(entry["entry"])
    idx=int(entry["entry_idx"])
    out.update({
        "m3v35_entry":round(price,10),
        "m3v35_entry_time":pd.Timestamp(entry["entry_time"]).isoformat(),
        "m3v35_entry_wait_bars":int(entry["wait_bars"]),
    })
    for key,value in _three_pct_outcome(fifteen,idx,price).items():
        out[key.replace("m3v2_","m3v35_")]=value
    return out
