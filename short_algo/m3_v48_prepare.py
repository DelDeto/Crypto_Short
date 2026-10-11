"""M3 V4.8 - fixed historical holdout for pre-registered structural-quality hypotheses."""
import hashlib,json,os
from datetime import datetime,timedelta,timezone
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import FROZEN_SYMBOLS,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v48_config import (
    M3_V48_PERIOD_START,M3_V48_PERIOD_END,M3_V48_FUTURE_END,
    M3_V48_BLOCK_DAYS,M3_V48_BLOCK_COUNT,M3_V48_HYPOTHESES,
    M3_V48_SHALLOW_RETEST_MAX_ATR15,M3_V48_CONTAINED_RISK_MAX_PCT,
    M3_V48_COMPACT_PULLBACK_BARS,
)

def build_manifest():
    assert_frozen_cohort(FROZEN_SYMBOLS)
    start=datetime.fromisoformat(M3_V48_PERIOD_START)
    blocks=[]
    for i in range(M3_V48_BLOCK_COUNT):
        bstart=start+timedelta(days=i*M3_V48_BLOCK_DAYS)
        bend=bstart+timedelta(days=M3_V48_BLOCK_DAYS)
        blocks.append({"block":i+1,"start":bstart.isoformat(),"end":bend.isoformat(),"days":M3_V48_BLOCK_DAYS})
    if blocks[-1]["end"]!=M3_V48_PERIOD_END:
        raise RuntimeError("V4.8 block layout mismatch")
    thresholds={
        "shallow_retest_max_atr15":M3_V48_SHALLOW_RETEST_MAX_ATR15,
        "contained_risk_max_pct":M3_V48_CONTAINED_RISK_MAX_PCT,
        "compact_pullback_bars":M3_V48_COMPACT_PULLBACK_BARS,
    }
    ident={
        "period_start":M3_V48_PERIOD_START,"period_end":M3_V48_PERIOD_END,
        "blocks":blocks,"symbols":list(FROZEN_SYMBOLS),
        "hypotheses":M3_V48_HYPOTHESES,"thresholds":thresholds,
    }
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":480,
        "manifest_id":f"m3v48-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":M3_V48_PERIOD_START,
        "period_end":M3_V48_PERIOD_END,
        "future_end":M3_V48_FUTURE_END,
        "block_days":M3_V48_BLOCK_DAYS,
        "block_count":M3_V48_BLOCK_COUNT,
        "blocks":blocks,
        "symbols":list(FROZEN_SYMBOLS),
        "symbol_count":FROZEN_SYMBOL_COUNT,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "hypotheses":M3_V48_HYPOTHESES,
        "thresholds":thresholds,
        "selection":"immutable cohort + fixed 2025 holdout; structural-quality hypotheses frozen from V4.7 before run",
        "research_status":"STRUCTURAL_QUALITY_HYPOTHESIS_HOLDOUT_NOT_FULL_STRATEGY_OOS",
        "caveat":"This 2025 window was previously used for exit-policy validation. It is independent for the V4.7 structural-quality hypotheses, but not untouched for the full strategy/exit lineage.",
    }

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v48_manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"],"thresholds":m["thresholds"],"hypotheses":m["hypotheses"]},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
