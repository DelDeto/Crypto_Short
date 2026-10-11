"""Freeze the V3.8-era 120-day window as structural-policy OOS.

Important: this is independent OOS for the V4.1 stop policy, but the base
setup/entry logic was already studied on this era in earlier M3 research.
Therefore this is not a fully untouched end-to-end OOS test.
"""
import json,os
from .config import OUTPUT_DIR
from .m3_v38_prepare import build_manifest as _build_v38

def build_manifest():
    m=_build_v38()
    m["manifest_version"]=420
    m["manifest_id"]="m3v42-"+m["manifest_id"].split("-",1)[-1]
    m["selection"]="current-turnover frozen cohort; V3.8-era structural-policy OOS"
    m["research_status"]="STRUCTURAL_POLICY_OOS_BASE_SETUP_PREEXPOSED_CURRENT_UNIVERSE_CAVEAT"
    return m

def main():
    m=build_manifest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v42_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({
        "manifest_id":m["manifest_id"],
        "period_start":m["period_start"],
        "period_end":m["period_end"],
        "block_days":m["block_days"],
        "block_count":m["block_count"],
        "symbols":m["symbol_count"],
    },indent=2))
    return 0 if m["symbol_count"] else 2

if __name__=="__main__":
    raise SystemExit(main())
