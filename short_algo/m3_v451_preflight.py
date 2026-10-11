"""M3 V4.5.1 preflight with immutable-cohort integrity checks."""
import json,os
from .config import OUTPUT_DIR
from .m3_v441_preflight import run_preflight
from .m3_v451_frozen_cohort import (
    SOURCE_MANIFEST_ID,SOURCE_PERIOD_START,SOURCE_PERIOD_END,FROZEN_SYMBOL_COUNT,
    FROZEN_SYMBOL_SHA256,assert_frozen_cohort,
)

def main():
    path=os.getenv("M3_V441_MANIFEST_PATH","output/m3_v451_manifest.json")
    with open(path,encoding="utf-8") as f:m=json.load(f)
    got_hash=assert_frozen_cohort(m.get("symbols") or [])
    integrity={
        "source_manifest_match":m.get("source_manifest_id")==SOURCE_MANIFEST_ID,
        "period_match":m.get("period_start")==SOURCE_PERIOD_START and m.get("period_end")==SOURCE_PERIOD_END,
        "symbol_count_match":int(m.get("symbol_count") or 0)==FROZEN_SYMBOL_COUNT,
        "symbol_hash_match":got_hash==FROZEN_SYMBOL_SHA256 and m.get("frozen_symbol_sha256")==FROZEN_SYMBOL_SHA256,
    }
    out=run_preflight(path)
    out["engine"]="M3 V4.5.1 Frozen Cohort Integrity"
    out["cohort_integrity"]=integrity
    out["data_valid"]=bool(out.get("data_valid") and all(integrity.values()))
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v451_preflight.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out.get("data_valid") else 2

if __name__=="__main__":raise SystemExit(main())
