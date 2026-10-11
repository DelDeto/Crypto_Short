"""M3 V4.2 — frozen V4.1 structural policy, no tuning."""
from .m3_v41_execution import evaluate_m3_v41
from .m3_v42_config import M3_V42_POLICY_NAME

def evaluate_m3_v42(one_closed,four_closed,fifteen,signal_time,btc_closed=None,eth_closed=None):
    base=evaluate_m3_v41(one_closed,four_closed,fifteen,signal_time,btc_closed,eth_closed)
    out={}
    for k,v in base.items():
        out[k.replace("m3v41_","m3v42_",1) if k.startswith("m3v41_") else k]=v

    if out.get("m3v42_state")!="STRUCTURAL_STUDY":
        return out

    policies=out.get("m3v42_policies") or {}
    frozen=policies.get(M3_V42_POLICY_NAME)
    out["m3v42_frozen_policy_name"]=M3_V42_POLICY_NAME
    out["m3v42_frozen_policy"]=frozen
    return out
