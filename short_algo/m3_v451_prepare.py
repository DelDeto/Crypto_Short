"""M3 V4.5.1 - build manifest from the exact V4.4.1 cohort; no live ranking calls."""
import hashlib,json,os
from datetime import datetime,timezone
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import (
    SOURCE_MANIFEST_ID,SOURCE_PERIOD_START,SOURCE_PERIOD_END,SOURCE_FUTURE_END,
    SOURCE_BLOCKS,FROZEN_SYMBOLS,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,
    assert_frozen_cohort,
)

def build_manifest():
    assert_frozen_cohort(FROZEN_SYMBOLS)
    ident={"period_start":SOURCE_PERIOD_START,"period_end":SOURCE_PERIOD_END,"blocks":SOURCE_BLOCKS,"symbols":list(FROZEN_SYMBOLS)}
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":451,
        "manifest_id":f"m3v451-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":SOURCE_PERIOD_START,
        "period_end":SOURCE_PERIOD_END,
        "future_end":SOURCE_FUTURE_END,
        "block_days":30,
        "block_count":len(SOURCE_BLOCKS),
        "blocks":SOURCE_BLOCKS,
        "symbols":list(FROZEN_SYMBOLS),
        "symbol_count":FROZEN_SYMBOL_COUNT,
        "selection":"immutable V4.4.1 cohort; no current-turnover reranking",
        "source_manifest_id":SOURCE_MANIFEST_ID,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "universe_audit":{"source":"V4.4.1 prepare artifact","source_manifest_id":SOURCE_MANIFEST_ID,"immutable":True},
        "research_status":"FROZEN_COHORT_REPLICATION_ONLY_NO_FILTER_PROMOTION",
    }

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    path=os.path.join(OUTPUT_DIR,"m3_v451_manifest.json")
    with open(path,"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:m[k] for k in ("manifest_id","source_manifest_id","period_start","period_end","symbol_count","frozen_symbol_sha256")},indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
