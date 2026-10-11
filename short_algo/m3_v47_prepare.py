"""M3 V4.7 - freeze the exact V4.6 OOS sample definition for failure attribution."""
import hashlib,json,os
from datetime import datetime,timedelta,timezone
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import FROZEN_SYMBOLS,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v47_config import (
    M3_V47_PERIOD_START,M3_V47_PERIOD_END,M3_V47_FUTURE_END,
    M3_V47_BLOCK_DAYS,M3_V47_BLOCK_COUNT,M3_V47_NUMERIC_BINS,
)

def build_manifest():
    assert_frozen_cohort(FROZEN_SYMBOLS)
    start=datetime.fromisoformat(M3_V47_PERIOD_START)
    blocks=[]
    for i in range(M3_V47_BLOCK_COUNT):
        bstart=start+timedelta(days=i*M3_V47_BLOCK_DAYS)
        bend=bstart+timedelta(days=M3_V47_BLOCK_DAYS)
        blocks.append({"block":i+1,"start":bstart.isoformat(),"end":bend.isoformat(),"days":M3_V47_BLOCK_DAYS})
    if blocks[-1]["end"]!=M3_V47_PERIOD_END:
        raise RuntimeError("V4.7 block layout mismatch")
    ident={
        "period_start":M3_V47_PERIOD_START,
        "period_end":M3_V47_PERIOD_END,
        "blocks":blocks,
        "symbols":list(FROZEN_SYMBOLS),
        "diagnostic_bins":M3_V47_NUMERIC_BINS,
    }
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":470,
        "manifest_id":f"m3v47-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":M3_V47_PERIOD_START,
        "period_end":M3_V47_PERIOD_END,
        "future_end":M3_V47_FUTURE_END,
        "block_days":M3_V47_BLOCK_DAYS,
        "block_count":M3_V47_BLOCK_COUNT,
        "blocks":blocks,
        "symbols":list(FROZEN_SYMBOLS),
        "symbol_count":FROZEN_SYMBOL_COUNT,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "diagnostic_bins":M3_V47_NUMERIC_BINS,
        "selection":"exact V4.6 OOS window and immutable cohort; diagnostic-only failure attribution",
        "research_status":"FAILURE_ATTRIBUTION_ONLY_NO_RULE_CHANGE_NO_FILTER_PROMOTION",
    }

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v47_manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"],"blocks":m["blocks"]},indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
