"""M3 V4.4.1 — frozen V4.4 strategy logic, renamed for clean reporting."""
from .m3_v44_execution import evaluate_m3_v44

def evaluate_m3_v441(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v44(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for k,v in base.items():
        out[k.replace("m3v44_","m3v441_",1) if k.startswith("m3v44_") else k]=v
    return out
