"""M3 V4.9 - build an expanding forward-shadow manifest from the post-V4.7 date."""
import hashlib,json,os,math
from datetime import datetime,timedelta,timezone
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import FROZEN_SYMBOLS,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v49_config import (
    M3_V49_FORWARD_START,M3_V49_SHALLOW_RETEST_MAX_ATR15,
    M3_V49_BLOCK_DAYS,M3_V49_EXIT_LOOKAHEAD_DAYS,
)

def _floor_hour(dt):
    return dt.replace(minute=0,second=0,microsecond=0)

def build_manifest(now=None):
    assert_frozen_cohort(FROZEN_SYMBOLS)
    now=_floor_hour(now or datetime.now(timezone.utc))
    start=datetime.fromisoformat(M3_V49_FORWARD_START)
    period_end=now-timedelta(days=int(M3_V49_EXIT_LOOKAHEAD_DAYS))
    if period_end<=start:
        raise RuntimeError("V4.9 forward window is not mature enough for 24h outcomes yet")
    future_end=now
    total_days=(period_end-start).total_seconds()/86400.0
    block_count=max(1,int(math.ceil(total_days/float(M3_V49_BLOCK_DAYS))))
    blocks=[]
    for i in range(block_count):
        bstart=start+timedelta(days=i*M3_V49_BLOCK_DAYS)
        bend=min(period_end,bstart+timedelta(days=M3_V49_BLOCK_DAYS))
        if bstart>=period_end:break
        blocks.append({"block":i+1,"start":bstart.isoformat(),"end":bend.isoformat(),"days":round((bend-bstart).total_seconds()/86400.0,5)})
    ident={
        "period_start":start.isoformat(),"period_end":period_end.isoformat(),
        "symbols":list(FROZEN_SYMBOLS),"blocks":blocks,
        "threshold":M3_V49_SHALLOW_RETEST_MAX_ATR15,
    }
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":490,
        "manifest_id":f"m3v49-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "period_start":start.isoformat(),
        "period_end":period_end.isoformat(),
        "future_end":future_end.isoformat(),
        "forward_days":round(total_days,5),
        "block_days":M3_V49_BLOCK_DAYS,
        "block_count":len(blocks),
        "blocks":blocks,
        "symbols":list(FROZEN_SYMBOLS),
        "symbol_count":FROZEN_SYMBOL_COUNT,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "hypothesis":{
            "id":"H1_SHALLOW_RETEST",
            "rule":f"retest_penetration_atr15 <= {M3_V49_SHALLOW_RETEST_MAX_ATR15}",
            "origin":"V4.7 diagnostic; V4.8 holdout validated",
        },
        "selection":"immutable V4.5.1 cohort; expanding post-2026-10-05 sequential forward shadow",
        "research_status":"FORWARD_SHADOW_ONLY_NO_RETUNING_NO_LIVE_PROMOTION",
    }

def main():
    m=build_manifest();os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    print(json.dumps({
        "manifest_id":m["manifest_id"],"period_start":m["period_start"],"period_end":m["period_end"],
        "forward_days":m["forward_days"],"blocks":m["blocks"],"symbols":m["symbol_count"],
        "hypothesis":m["hypothesis"],
    },ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
