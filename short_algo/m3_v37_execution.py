"""M3 V3.7 — frozen context candidates on a second temporal OOS window.

Reuses the frozen V3.6 base setup/POI-limit execution, then applies only the
three context rules selected before this run. No thresholds are tuned here.
"""
from .m3_v36_execution import evaluate_m3_v36
from .m3_v37_config import M3_V37_RW24_MAX, M3_V37_VOLUME_MIN


def evaluate_m3_v37(one_closed, four_closed, fifteen, signal_time, btc_closed=None, eth_closed=None):
    base=evaluate_m3_v36(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)

    out={}
    for key,value in base.items():
        if key.startswith("m3v36_"):
            out[key.replace("m3v36_","m3v37_",1)]=value
        else:
            out[key]=value

    if out.get("m3v37_state")!="BASELINE_CANDIDATE":
        return out

    rw24=float(out.get("m3v37_relative_weakness_24h_pct") or 0.0)
    vol=float(out.get("m3v37_volume_expansion_1h") or 0.0)

    out["m3v37_candidate_a_rw24_le_m5"]=int(rw24<=float(M3_V37_RW24_MAX))
    out["m3v37_candidate_b_volume_ge_2"]=int(vol>=float(M3_V37_VOLUME_MIN))
    out["m3v37_candidate_c_both"]=int(
        rw24<=float(M3_V37_RW24_MAX) and vol>=float(M3_V37_VOLUME_MIN)
    )
    return out
