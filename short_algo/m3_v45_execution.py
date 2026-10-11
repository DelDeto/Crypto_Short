"""M3 V4.5 — exact V4.4.1 strategy, diagnostics only."""
from .m3_v441_execution import evaluate_m3_v441

def evaluate_m3_v45(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v441(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for k,v in base.items():
        out[k.replace("m3v441_","m3v45_",1) if k.startswith("m3v441_") else k]=v
    return out
