"""Freeze V4.1 structural-risk development window.

Uses the same historical era as V3.9/V4.0 on purpose: this is development,
not independent validation. Any selected policy must later pass a new OOS run.
"""
import json,os
from .config import OUTPUT_DIR
from .m3_v40_prepare import build_manifest as _build_v40

def build_manifest():
    m=_build_v40()
    m["manifest_version"]=410
    m["manifest_id"]="m3v41-"+m["manifest_id"].split("-",1)[-1]
    m["research_status"]="SAME_PERIOD_TRUE_STRUCTURAL_RISK_DEVELOPMENT_CURRENT_UNIVERSE_CAVEAT"
    m["selection"]="current-turnover frozen cohort; V3.9/V4.0-era true-structural-risk development"
    return m

def main():
    m=build_manifest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v41_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"]},indent=2))
    return 0 if m["symbol_count"] else 2

if __name__=="__main__":
    raise SystemExit(main())
