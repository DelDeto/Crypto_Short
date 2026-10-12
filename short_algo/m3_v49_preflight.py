"""M3 V4.9.1: immutable H1 anchor, dependency-aware preflight and safe warm-up."""
import json,os
from datetime import datetime
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_CONTEXT_COVERAGE
from .m3_v441_preflight import _coverage
from .m3_v451_frozen_cohort import FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v49_config import (
    M3_V49_FORWARD_START,M3_V49_FREEZE_COMMIT,M3_V49_EVIDENCE_CLASS,
    M3_V49_SHALLOW_RETEST_MAX_ATR15,
)
from .mexc import get_klines_window

def main():
    path=os.getenv("M3_V49_MANIFEST_PATH","output/m3_v49_manifest.json")
    with open(path,encoding="utf-8") as f:m=json.load(f)
    got_hash=assert_frozen_cohort(m.get("symbols") or [])
    hyp=m.get("hypothesis") or {}
    start=datetime.fromisoformat(m["period_start"])
    end=datetime.fromisoformat(m["period_end"])
    ready=bool(m.get("window_ready"))
    integrity={
        "prospective_start_frozen":m.get("period_start")==M3_V49_FORWARD_START,
        "freeze_commit_match":m.get("research_freeze_commit")==M3_V49_FREEZE_COMMIT,
        "evidence_label_match":m.get("evidence_class")==M3_V49_EVIDENCE_CLASS,
        "symbol_count_match":int(m.get("symbol_count") or 0)==FROZEN_SYMBOL_COUNT,
        "symbol_hash_match":got_hash==FROZEN_SYMBOL_SHA256 and m.get("frozen_symbol_sha256")==FROZEN_SYMBOL_SHA256,
        "hypothesis_id_match":hyp.get("id")=="H1_SHALLOW_RETEST",
        "threshold_exact_match":hyp.get("threshold_atr15")==M3_V49_SHALLOW_RETEST_MAX_ATR15,
        "period_not_pre_freeze":start>=datetime.fromisoformat(M3_V49_FORWARD_START),
        "window_status_consistent":(end>start)==ready,
        "exit_maturity_safe":(not ready) or datetime.fromisoformat(m["future_end"])>=end,
    }
    if not all(integrity.values()):
        raise RuntimeError(f"V4.9.1 integrity FAIL: {integrity}")

    # A fresh run before the first 48h outcome matures is a valid WAIT,
    # not a backtest failure and not statistical evidence.
    context={};context_ok=False
    if ready:
        context_ok=True
        for symbol in ("BTC_USDT","ETH_USDT"):
            try:
                frame=get_klines_window(symbol,"1h",m["period_start"],m["period_end"])
                stat=_coverage(frame,m["period_start"],m["period_end"],60)
            except Exception as exc:
                stat={"bars":0,"expected":0,"coverage":0.0,"first":None,"last":None,"error":str(exc)}
            context[symbol]={"1h":stat}
            if float(stat.get("coverage") or 0.0)<float(M3_V441_MIN_CONTEXT_COVERAGE):
                context_ok=False
    out={
        "manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],
        "evaluation_ready":ready,
        "minimum_context_coverage":float(M3_V441_MIN_CONTEXT_COVERAGE),
        "context_dependencies":["BTC_USDT:1h","ETH_USDT:1h"],
        "context":context,"integrity":integrity,
        "engine":"M3 V4.9.1 Prospective Replay Shadow",
        "data_valid":bool(ready and context_ok and all(integrity.values())),
        "research_status":"READY_FOR_REPLAY" if ready else "WAITING_FOR_MATURE_FORWARD_WINDOW",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_preflight.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if (not ready or out["data_valid"]) else 2

if __name__=="__main__":raise SystemExit(main())
