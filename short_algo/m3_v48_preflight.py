"""M3 V4.8 preflight: validate only context dependencies actually consumed by the replay engine."""
import json,os
from .config import OUTPUT_DIR
from .m3_v441_config import M3_V441_MIN_CONTEXT_COVERAGE
from .m3_v441_preflight import _coverage
from .m3_v451_frozen_cohort import FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v48_config import (
    M3_V48_PERIOD_START,M3_V48_PERIOD_END,M3_V48_BLOCK_COUNT,M3_V48_HYPOTHESES,
    M3_V48_SHALLOW_RETEST_MAX_ATR15,M3_V48_CONTAINED_RISK_MAX_PCT,
    M3_V48_COMPACT_PULLBACK_BARS,
)
from .mexc import get_klines_window

def main():
    path=os.getenv("M3_V441_MANIFEST_PATH","output/m3_v48_manifest.json")
    with open(path,encoding="utf-8") as f:m=json.load(f)
    got_hash=assert_frozen_cohort(m.get("symbols") or [])
    expected_thresholds={
        "shallow_retest_max_atr15":M3_V48_SHALLOW_RETEST_MAX_ATR15,
        "contained_risk_max_pct":M3_V48_CONTAINED_RISK_MAX_PCT,
        "compact_pullback_bars":M3_V48_COMPACT_PULLBACK_BARS,
    }
    integrity={
        "period_match":m.get("period_start")==M3_V48_PERIOD_START and m.get("period_end")==M3_V48_PERIOD_END,
        "block_count_match":int(m.get("block_count") or 0)==int(M3_V48_BLOCK_COUNT),
        "symbol_count_match":int(m.get("symbol_count") or 0)==FROZEN_SYMBOL_COUNT,
        "symbol_hash_match":got_hash==FROZEN_SYMBOL_SHA256 and m.get("frozen_symbol_sha256")==FROZEN_SYMBOL_SHA256,
        "hypotheses_match":m.get("hypotheses")==M3_V48_HYPOTHESES,
        "thresholds_match":m.get("thresholds")==expected_thresholds,
    }

    # V4.5/V4.6/V4.7/V4.8 replay passes only BTC/ETH 1h context into the
    # strategy engine. 15m/4h BTC/ETH are not consumed, so requiring them
    # would create a false-negative preflight on older windows.
    context={}
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
        "manifest_id":m["manifest_id"],
        "period_start":m["period_start"],
        "period_end":m["period_end"],
        "minimum_context_coverage":float(M3_V441_MIN_CONTEXT_COVERAGE),
        "context_dependencies":["BTC_USDT:1h","ETH_USDT:1h"],
        "context":context,
        "engine":"M3 V4.8 Structural Quality Holdout",
        "integrity":integrity,
        "data_valid":bool(context_ok and all(integrity.values())),
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v48_preflight.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out.get("data_valid") else 2

if __name__=="__main__":raise SystemExit(main())
