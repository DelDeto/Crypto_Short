"""M3 V4.4 frozen fixed 1.5R exit validation."""
from .m3_v43_execution import evaluate_m3_v43
from .m3_v44_config import M3_V44_EXIT_VARIANT

def evaluate_m3_v44(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v43(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for k,v in base.items():
        out[k.replace("m3v43_","m3v44_",1) if k.startswith("m3v43_") else k]=v
    if out.get("m3v44_exit_state")!="EXIT_STUDY":
        return out
    variants=out.get("m3v44_exit_variants") or {}
    out["m3v44_frozen_exit_name"]=M3_V44_EXIT_VARIANT
    out["m3v44_frozen_exit"]=variants.get(M3_V44_EXIT_VARIANT)
    return out
