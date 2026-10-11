"""Create a fixed-date manifest for M3 V4.4.1."""
import hashlib,json,os
from datetime import datetime,timedelta,timezone

from .config import BACKTEST_SYMBOL_LIMIT,OUTPUT_DIR
from .m3_v441_config import (
    M3_V441_PERIOD_START,M3_V441_PERIOD_END,M3_V441_FUTURE_END,
    M3_V441_BLOCK_DAYS,M3_V441_BLOCK_COUNT,
)
from .mexc import get_all_tickers,get_contract_universe

def build_manifest(symbol_limit=None):
    symbol_limit=int(BACKTEST_SYMBOL_LIMIT if symbol_limit is None else symbol_limit)
    universe,audit=get_contract_universe(return_audit=True)
    tickers=get_all_tickers()
    ranked=sorted(
        [s for s in universe if s in tickers],
        key=lambda s:-float((tickers.get(s) or {}).get("turnover_24h") or 0.0),
    )
    if symbol_limit>0:
        ranked=ranked[:symbol_limit]

    start=datetime.fromisoformat(M3_V441_PERIOD_START)
    blocks=[]
    for i in range(M3_V441_BLOCK_COUNT):
        bstart=start+timedelta(days=i*M3_V441_BLOCK_DAYS)
        bend=bstart+timedelta(days=M3_V441_BLOCK_DAYS)
        blocks.append({"block":i+1,"start":bstart.isoformat(),"end":bend.isoformat(),"days":M3_V441_BLOCK_DAYS})

    ident={"period_start":M3_V441_PERIOD_START,"period_end":M3_V441_PERIOD_END,"blocks":blocks,"symbols":ranked}
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":441,
        "manifest_id":f"m3v441-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":M3_V441_PERIOD_START,
        "period_end":M3_V441_PERIOD_END,
        "future_end":M3_V441_FUTURE_END,
        "block_days":M3_V441_BLOCK_DAYS,
        "block_count":M3_V441_BLOCK_COUNT,
        "blocks":blocks,
        "symbols":ranked,
        "symbol_count":len(ranked),
        "selection":"current-turnover frozen cohort; fixed-date exit-policy OOS with coverage guard",
        "universe_audit":audit,
        "research_status":"FROZEN_EXIT_POLICY_OOS_BASE_SETUP_PREEXPOSED_CURRENT_UNIVERSE_CAVEAT",
    }

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v441_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"],"blocks":m["blocks"]},indent=2))
    return 0 if m["symbol_count"] else 2

if __name__=="__main__":
    raise SystemExit(main())
