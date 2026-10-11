"""M3 V4.0 shard writer."""
import json,os,sys
from .config import OUTPUT_DIR
from .m3_v40_backtest import run_m3_v40_backtest

def main():
    report=run_m3_v40_backtest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v40_backtest.json"),"w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    print(json.dumps({"manifest_id":report["manifest_id"],"shard":report["shard_index"],"symbols":report["selected_symbol_count"],"rows":len(report["rows"]),"errors":len(report["errors"])},indent=2))
    return 0 if report["selected_symbol_count"] else 2

if __name__=="__main__":
    sys.exit(main())
