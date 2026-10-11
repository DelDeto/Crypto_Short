"""M3 V4.6 - fixed sequential OOS manifest using the immutable V4.4.1 cohort."""
import hashlib,json,os
from datetime import datetime,timedelta,timezone
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import FROZEN_SYMBOLS,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v46_config import (
    M3_V46_PERIOD_START,M3_V46_PERIOD_END,M3_V46_FUTURE_END,
    M3_V46_BLOCK_DAYS,M3_V46_BLOCK_COUNT,M3_V46_HYPOTHESES,
)

def build_manifest():
    assert_frozen_cohort(FROZEN_SYMBOLS)
    start=datetime.fromisoformat(M3_V46_PERIOD_START)
    blocks=[]
    for i in range(M3_V46_BLOCK_COUNT):
        bstart=start+timedelta(days=i*M3_V46_BLOCK_DAYS)
        bend=bstart+timedelta(days=M3_V46_BLOCK_DAYS)
        blocks.append({"block":i+1,"start":bstart.isoformat(),"end":bend.isoformat(),"days":M3_V46_BLOCK_DAYS})
    if blocks[-1]["end"]!=M3_V46_PERIOD_END:
        raise RuntimeError(f"Block layout does not end at frozen period_end: {blocks[-1]['end']} != {M3_V46_PERIOD_END}")
    ident={"period_start":M3_V46_PERIOD_START,"period_end":M3_V46_PERIOD_END,"blocks":blocks,"symbols":list(FROZEN_SYMBOLS),"hypotheses":M3_V46_HYPOTHESES}
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":460,
        "manifest_id":f"m3v46-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":M3_V46_PERIOD_START,
        "period_end":M3_V46_PERIOD_END,
        "future_end":M3_V46_FUTURE_END,
        "block_days":M3_V46_BLOCK_DAYS,
        "block_count":M3_V46_BLOCK_COUNT,
        "blocks":blocks,
        "symbols":list(FROZEN_SYMBOLS),
        "symbol_count":FROZEN_SYMBOL_COUNT,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "hypotheses":M3_V46_HYPOTHESES,
        "selection":"immutable V4.4.1 cohort; sequential OOS window for frozen regime hypotheses",
        "research_status":"REGIME_HYPOTHESIS_OOS_ONLY_NOT_LIVE_PROMOTION",
        "caveat":"OOS for regime hypotheses only; base strategy lineage and current-universe survivorship remain pre-exposed caveats.",
    }

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v46_manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"],"blocks":m["blocks"],"hypotheses":m["hypotheses"]},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
