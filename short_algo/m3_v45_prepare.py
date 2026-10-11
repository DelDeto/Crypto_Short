"""Reuse the fixed V4.4.1 window for diagnostic attribution only."""
import json,os
from .config import OUTPUT_DIR
from .m3_v441_prepare import build_manifest as _build_v441

def build_manifest():
    m=_build_v441()
    m["manifest_version"]=450
    m["manifest_id"]="m3v45-"+m["manifest_id"].split("-",1)[-1]
    m["selection"]="current-turnover frozen cohort; fixed-window regime attribution"
    m["research_status"]="REGIME_ATTRIBUTION_DIAGNOSTIC_ONLY_CURRENT_UNIVERSE_CAVEAT"
    return m

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v45_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"]},indent=2))
    return 0 if m["symbol_count"] else 2

if __name__=="__main__":raise SystemExit(main())
