"""M3 V4.9 preflight: frozen cohort/hypothesis plus actual BTC/ETH 1h dependency coverage."""
import json,os
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_CONTEXT_COVERAGE
from .m3_v441_preflight import _coverage
from .m3_v451_frozen_cohort import FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v49_config import M3_V49_FORWARD_START,M3_V49_SHALLOW_RETEST_MAX_ATR15
from .mexc import get_klines_window

def main():
    path=os.getenv("M3_V49_MANIFEST_PATH","output/m3_v49_manifest.json")
    with open(path,encoding="utf-8") as f:m=json.load(f)
    got_hash=assert_frozen_cohort(m.get("symbols") or [])
    hyp=m.get("hypothesis") or {}
    integrity={
        "forward_start_match":m.get("period_start")==M3_V49_FORWARD_START,
        "symbol_count_match":int(m.get("symbol_count") or 0)==FROZEN_SYMBOL_COUNT,
        "symbol_hash_match":got_hash==FROZEN_SYMBOL_SHA256 and m.get("frozen_symbol_sha256")==FROZEN_SYMBOL_SHA256,
        "hypothesis_id_match":hyp.get("id")=="H1_SHALLOW_RETEST",
        "threshold_frozen":str(M3_V49_SHALLOW_RETEST_MAX_ATR15) in str(hyp.get("rule")),
    }
    context={};context_ok=True
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
        "minimum_context_coverage":float(M3_V441_MIN_CONTEXT_COVERAGE),
        "context_dependencies":["BTC_USDT:1h","ETH_USDT:1h"],
        "context":context,"integrity":integrity,
        "engine":"M3 V4.9 Shallow Retest Forward Shadow",
        "data_valid":bool(context_ok and all(integrity.values())),
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_preflight.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out["data_valid"] else 2

if __name__=="__main__":raise SystemExit(main())
