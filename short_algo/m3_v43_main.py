"""M3 V4.3 shard writer."""
import json,os,sys
from .config import OUTPUT_DIR
from .m3_v43_backtest import run_m3_v43_backtest
def main():
    r=run_m3_v43_backtest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v43_backtest.json"),"w",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2,default=str)
    print(json.dumps({"manifest_id":r["manifest_id"],"shard":r["shard_index"],"symbols":r["selected_symbol_count"],"rows":len(r["rows"]),"errors":len(r["errors"])},indent=2))
    return 0 if r["selected_symbol_count"] else 2
if __name__=="__main__":sys.exit(main())
