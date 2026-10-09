"""M3 V3.4 — setup-quality decomposition with V3.3 Entry B fixed.

Research only. Setup generation remains V2.1-derived. Execution is fixed to the
V3.3 POI-limit benchmark so this study isolates setup quality rather than entry
style.
"""
import pandas as pd

from .m3_v21_execution import evaluate_m3_v21
from .m3_v2_execution import _find_displacement_retest, _three_pct_outcome
from .m3_v34_config import (
    M3_V34_LIMIT_FILL_BARS,
    M3_V34_MAX_TARGET_ATR,
    M3_V34_MIN_RETEST_QUALITY,
)


def _entry_b(fifteen, seq):
    if seq.get("state") != "RETEST_ENTRY":
        return {"state": "NO_ENTRY"}
    frame=fifteen.sort_index()
    first_i=int(seq["entry_idx"])
    poi=float(seq["break_level"])
    last_i=min(len(frame)-1, first_i+int(M3_V34_LIMIT_FILL_BARS)-1)
    for i in range(first_i,last_i+1):
        if float(frame.iloc[i]["high"]) >= poi:
            return {
                "state":"FILLED",
                "entry":poi,
                "entry_idx":i,
                "entry_time":frame.index[i],
                "wait_bars":i-first_i,
            }
    return {"state":"NO_FILL"}


def evaluate_m3_v34(one_closed,four_closed,fifteen,signal_time):
    out=evaluate_m3_v21(one_closed,four_closed,fifteen,signal_time)
    if out.get("m3v21_state")!="ENTRY_BENCHMARK":
        out["m3v34_state"]="NO_BASE_ENTRY"
        return out

    quality=int(out.get("m3v21_retest_quality_score") or 0)
    target_atr=float(out.get("m3v2_target3_atr") or 99.0)
    core=bool(
        out.get("m3v2_poi_source")=="BROKEN_SUPPORT_1H"
        and quality>=int(M3_V34_MIN_RETEST_QUALITY)
        and target_atr<=float(M3_V34_MAX_TARGET_ATR)
    )
    out["m3v34_core_gate_pass"]=int(core)
    if not core:
        out["m3v34_state"]="FAIL_CORE"
        return out

    seq=_find_displacement_retest(fifteen,signal_time)
    if seq.get("state")!="RETEST_ENTRY":
        out["m3v34_state"]="NO_RETEST"
        return out

    entry=_entry_b(fifteen,seq)
    out.update({
        "m3v34_state":"CORE_CANDIDATE",
        "m3v34_poi":round(float(seq["break_level"]),10),
        "m3v34_displacement_body_atr15":round(float(seq["displacement_body_atr15"]),5),
        "m3v34_base_chase_atr15":round(float(seq["chase_atr15"]),5),
        "m3v34_entry_state":entry.get("state"),
    })
    if entry.get("state")!="FILLED":
        return out

    price=float(entry["entry"])
    idx=int(entry["entry_idx"])
    out.update({
        "m3v34_entry":round(price,10),
        "m3v34_entry_time":pd.Timestamp(entry["entry_time"]).isoformat(),
        "m3v34_entry_wait_bars":int(entry["wait_bars"]),
    })
    for key,value in _three_pct_outcome(fifteen,idx,price).items():
        out[key.replace("m3v2_","m3v34_")]=value
    return out
