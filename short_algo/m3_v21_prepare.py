"""Freeze M3 V2.1 research cohort."""
import hashlib,json,os
from datetime import datetime,timedelta,timezone
from .config import BACKTEST_SYMBOL_LIMIT,OUTPUT_DIR
from .m3_v21_config import M3_V21_DAYS
from .mexc import get_all_tickers,get_contract_universe
def build_manifest(days=None,symbol_limit=None):
    days=int(days or M3_V21_DAYS);symbol_limit=int(BACKTEST_SYMBOL_LIMIT if symbol_limit is None else symbol_limit)
    pe=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(days=2);ps=pe-timedelta(days=days);fe=pe+timedelta(days=2)
    universe,audit=get_contract_universe(return_audit=True);tickers=get_all_tickers()
    ranked=sorted([s for s in universe if s in tickers],key=lambda s:-float((tickers.get(s) or {}).get("turnover_24h") or 0.0))
    if symbol_limit>0:ranked=ranked[:symbol_limit]
    ident={"period_start":ps.isoformat(),"period_end":pe.isoformat(),"future_end":fe.isoformat(),"days":days,"symbols":ranked}
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {"manifest_version":321,"manifest_id":f"m3v21-{digest}","created_at":datetime.now(timezone.utc).isoformat(),"period_start":ps.isoformat(),"period_end":pe.isoformat(),"future_end":fe.isoformat(),"days":days,"symbols":ranked,"symbol_count":len(ranked),"selection":"frozen_current_turnover_rank_crypto_only","universe_audit":audit}
def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v21_manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({"manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],"symbols":m["symbol_count"]},indent=2));return 0 if m["symbol_count"] else 2
if __name__=="__main__":raise SystemExit(main())
