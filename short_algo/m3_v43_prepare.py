"""Use the V4.2 120-day era as exit-architecture development data."""
import json,os
from .config import OUTPUT_DIR
from .m3_v42_prepare import build_manifest as _build_v42

def build_manifest():
    m=_build_v42()
    m["manifest_version"]=430
    m["manifest_id"]="m3v43-"+m["manifest_id"].split("-",1)[-1]
    m["selection"]="current-turnover frozen cohort; V4.2-era exit-architecture development"
    m["research_status"]="SAME_PERIOD_EXIT_ARCHITECTURE_DEVELOPMENT_CURRENT_UNIVERSE_CAVEAT"
    return m

def main():
    m=build_manifest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v43_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"]},indent=2))
    return 0 if m["symbol_count"] else 2

if __name__=="__main__":
    raise SystemExit(main())
