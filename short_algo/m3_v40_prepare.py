"""Reuse the V3.9-era 120-day study window for structural-stop development."""
import hashlib, json, os
from datetime import datetime, timedelta, timezone

from .config import BACKTEST_SYMBOL_LIMIT, OUTPUT_DIR
from .m3_v40_config import (
    M3_V40_BLOCK_COUNT, M3_V40_BLOCK_DAYS, M3_V40_DEV_DAYS,
    M3_V40_OOS1_DAYS, M3_V40_OOS2_DAYS, M3_V40_V38_DAYS, M3_V40_EMBARGO_DAYS,
)
from .mexc import get_all_tickers, get_contract_universe


def build_manifest(symbol_limit=None):
    symbol_limit=int(BACKTEST_SYMBOL_LIMIT if symbol_limit is None else symbol_limit)
    anchor=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(days=2)
    dev_start=anchor-timedelta(days=M3_V40_DEV_DAYS)
    oos1_start=dev_start-timedelta(days=M3_V40_EMBARGO_DAYS+M3_V40_OOS1_DAYS)
    oos2_start=oos1_start-timedelta(days=M3_V40_EMBARGO_DAYS+M3_V40_OOS2_DAYS)
    v38_start=oos2_start-timedelta(days=M3_V40_EMBARGO_DAYS+M3_V40_V38_DAYS)
    period_end=v38_start-timedelta(days=M3_V40_EMBARGO_DAYS)
    total_days=M3_V40_BLOCK_COUNT*M3_V40_BLOCK_DAYS
    period_start=period_end-timedelta(days=total_days)
    future_end=period_end+timedelta(days=2)

    blocks=[]
    for i in range(M3_V40_BLOCK_COUNT):
        start=period_start+timedelta(days=i*M3_V40_BLOCK_DAYS)
        end=start+timedelta(days=M3_V40_BLOCK_DAYS)
        blocks.append({"block":i+1,"start":start.isoformat(),"end":end.isoformat(),"days":M3_V40_BLOCK_DAYS})

    universe,audit=get_contract_universe(return_audit=True)
    tickers=get_all_tickers()
    ranked=sorted([s for s in universe if s in tickers], key=lambda s:-float((tickers.get(s) or {}).get("turnover_24h") or 0.0))
    if symbol_limit>0:
        ranked=ranked[:symbol_limit]

    ident={"period_start":period_start.isoformat(),"period_end":period_end.isoformat(),"blocks":blocks,"symbols":ranked}
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":400,
        "manifest_id":f"m3v40-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":period_start.isoformat(),
        "period_end":period_end.isoformat(),
        "future_end":future_end.isoformat(),
        "block_days":M3_V40_BLOCK_DAYS,
        "block_count":M3_V40_BLOCK_COUNT,
        "blocks":blocks,
        "symbols":ranked,
        "symbol_count":len(ranked),
        "selection":"current-turnover frozen cohort; V3.9-era stop-design window",
        "universe_audit":audit,
        "research_status":"SAME_PERIOD_STRUCTURAL_STOP_DEVELOPMENT_CURRENT_UNIVERSE_CAVEAT",
    }


def main():
    manifest=build_manifest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v40_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":manifest["manifest_id"],"period_start":manifest["period_start"],"period_end":manifest["period_end"],"symbols":manifest["symbol_count"]},indent=2))
    return 0 if manifest["symbol_count"] else 2


if __name__=="__main__":
    raise SystemExit(main())
