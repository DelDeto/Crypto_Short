"""Freeze M3 V3.3 research cohort."""
import hashlib, json, os
from datetime import datetime, timedelta, timezone
from .config import BACKTEST_SYMBOL_LIMIT, OUTPUT_DIR
from .m3_v33_config import M3_V33_DAYS
from .mexc import get_all_tickers, get_contract_universe

def build_manifest(days=None, symbol_limit=None):
    days=int(days or M3_V33_DAYS)
    symbol_limit=int(BACKTEST_SYMBOL_LIMIT if symbol_limit is None else symbol_limit)
    period_end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(days=2)
    period_start=period_end-timedelta(days=days)
    future_end=period_end+timedelta(days=2)
    universe,audit=get_contract_universe(return_audit=True)
    tickers=get_all_tickers()
    ranked=sorted([s for s in universe if s in tickers],key=lambda s:-float((tickers.get(s) or {}).get("turnover_24h") or 0.0))
    if symbol_limit>0:
        ranked=ranked[:symbol_limit]
    ident={"period_start":period_start.isoformat(),"period_end":period_end.isoformat(),"future_end":future_end.isoformat(),"days":days,"symbols":ranked}
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {"manifest_version":333,"manifest_id":f"m3v33-{digest}","created_at":datetime.now(timezone.utc).isoformat(),"period_start":period_start.isoformat(),"period_end":period_end.isoformat(),"future_end":future_end.isoformat(),"days":days,"symbols":ranked,"symbol_count":len(ranked),"selection":"frozen current turnover cohort","universe_audit":audit,"research_status":"SAME_PERIOD_DEVELOPMENT_NOT_OOS"}

def main():
    manifest=build_manifest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v33_manifest.json"),"w",encoding="utf-8") as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":manifest["manifest_id"],"period_start":manifest["period_start"],"period_end":manifest["period_end"],"symbols":manifest["symbol_count"]},indent=2))
    return 0 if manifest["symbol_count"] else 2

if __name__=="__main__":
    raise SystemExit(main())
