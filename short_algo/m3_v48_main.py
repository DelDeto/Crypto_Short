"""M3 V4.8 shard replay. Strategy engine remains identical to V4.6/V4.7."""
import json,os,sys
from .config import OUTPUT_DIR
from .m3_v45_backtest import run_m3_v45_backtest

def main():
    path=os.getenv("M3_V48_MANIFEST_PATH","frozen/m3_v48_manifest.json")
    r=run_m3_v45_backtest(path)
    r["engine"]="M3 V4.8 Structural Quality Holdout"
    r["validation_scope"]="pre_registered_structural_quality_hypotheses_only"
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v48_backtest.json"),"w",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2,default=str)
    print(json.dumps({"manifest_id":r["manifest_id"],"shard":r["shard_index"],"symbols":r["selected_symbol_count"],"eligible_symbols":r["eligible_symbol_count"],"rows":len(r["rows"]),"errors":len(r["errors"])},indent=2))
    return 0 if r["selected_symbol_count"] else 2

if __name__=="__main__":sys.exit(main())
