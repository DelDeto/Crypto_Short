"""M3 V4.6 preflight: OOS dates + immutable cohort + BTC/ETH context coverage."""
import json,os
from .config import OUTPUT_DIR
from .m3_v441_preflight import run_preflight
from .m3_v451_frozen_cohort import FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v46_config import M3_V46_PERIOD_START,M3_V46_PERIOD_END,M3_V46_BLOCK_COUNT,M3_V46_HYPOTHESES

def main():
    path=os.getenv("M3_V441_MANIFEST_PATH","output/m3_v46_manifest.json")
    with open(path,encoding="utf-8") as f:m=json.load(f)
    got_hash=assert_frozen_cohort(m.get("symbols") or [])
    integrity={
        "period_match":m.get("period_start")==M3_V46_PERIOD_START and m.get("period_end")==M3_V46_PERIOD_END,
        "block_count_match":int(m.get("block_count") or 0)==int(M3_V46_BLOCK_COUNT),
        "symbol_count_match":int(m.get("symbol_count") or 0)==FROZEN_SYMBOL_COUNT,
        "symbol_hash_match":got_hash==FROZEN_SYMBOL_SHA256 and m.get("frozen_symbol_sha256")==FROZEN_SYMBOL_SHA256,
        "hypotheses_match":m.get("hypotheses")==M3_V46_HYPOTHESES,
    }
    out=run_preflight(path)
    out["engine"]="M3 V4.6 Frozen Regime OOS"
    out["integrity"]=integrity
    out["data_valid"]=bool(out.get("data_valid") and all(integrity.values()))
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v46_preflight.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out.get("data_valid") else 2

if __name__=="__main__":raise SystemExit(main())
