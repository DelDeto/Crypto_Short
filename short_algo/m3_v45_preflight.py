"""M3 V4.5 data preflight; strategy-neutral diagnostic QA."""
import json,os
from .config import OUTPUT_DIR
from .m3_v441_preflight import run_preflight

def main():
    out=run_preflight(os.getenv("M3_V441_MANIFEST_PATH","output/m3_v45_manifest.json"))
    out["engine"]="M3 V4.5 Regime Attribution"
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v45_preflight.json"),"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out.get("data_valid") else 2

if __name__=="__main__":raise SystemExit(main())
