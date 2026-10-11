"""M3 V3.8 — frozen V3.7 context rules, unchanged execution."""
from .m3_v37_execution import evaluate_m3_v37


def evaluate_m3_v38(one_closed, four_closed, fifteen, signal_time, btc_closed=None, eth_closed=None):
    base=evaluate_m3_v37(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for key,value in base.items():
        if key.startswith("m3v37_"):
            out[key.replace("m3v37_","m3v38_",1)]=value
        else:
            out[key]=value
    return out
