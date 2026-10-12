"""M3 V4.9.1 - prospective shadow manifest; no pre-freeze trades enter validation."""
import hashlib,json,os,math
from datetime import datetime,timedelta,timezone
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import FROZEN_SYMBOLS,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort
from .m3_v49_config import (
    M3_V49_FORWARD_START,M3_V49_FREEZE_COMMIT,M3_V49_EVIDENCE_CLASS,
    M3_V49_SHALLOW_RETEST_MAX_ATR15,M3_V49_BLOCK_DAYS,M3_V49_EXIT_LOOKAHEAD_DAYS,
)

def _floor_hour(dt):
    return dt.astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)

def build_manifest(now=None):
    assert_frozen_cohort(FROZEN_SYMBOLS)
    now=_floor_hour(now or datetime.now(timezone.utc))
    start=datetime.fromisoformat(M3_V49_FORWARD_START)
    mature_until=now-timedelta(days=int(M3_V49_EXIT_LOOKAHEAD_DAYS))
    ready=mature_until>start
    end=mature_until if ready else start
    forward_days=max(0.0,(end-start).total_seconds()/86400.0)
    count=int(math.ceil(forward_days/float(M3_V49_BLOCK_DAYS))) if ready else 0
    blocks=[]
    for i in range(count):
        bstart=start+timedelta(days=i*M3_V49_BLOCK_DAYS)
        bend=min(end,bstart+timedelta(days=M3_V49_BLOCK_DAYS))
        if bstart>=end:break
        blocks.append({"block":i+1,"start":bstart.isoformat(),"end":bend.isoformat(),"days":round((bend-bstart).total_seconds()/86400.0,5)})

    ident={
        "period_start":start.isoformat(),"period_end":end.isoformat(),
        "symbols":list(FROZEN_SYMBOLS),"blocks":blocks,
        "threshold":M3_V49_SHALLOW_RETEST_MAX_ATR15,
        "freeze_commit":M3_V49_FREEZE_COMMIT,
    }
    digest=hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "manifest_version":491,
        "manifest_id":f"m3v491-{digest}",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "manifest_status":"READY_FOR_REPLAY" if ready else "WAITING_FOR_MATURE_FORWARD_WINDOW",
        "window_ready":ready,
        "period_start":start.isoformat(),
        "period_end":end.isoformat(),
        "future_end":now.isoformat(),
        "forward_days":round(forward_days,5),
        "block_days":M3_V49_BLOCK_DAYS,
        "block_count":len(blocks),
        "blocks":blocks,
        "symbols":list(FROZEN_SYMBOLS),
        "symbol_count":FROZEN_SYMBOL_COUNT,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "research_freeze_commit":M3_V49_FREEZE_COMMIT,
        "evidence_class":M3_V49_EVIDENCE_CLASS,
        "hypothesis":{
            "id":"H1_SHALLOW_RETEST",
            "rule":f"retest_penetration_atr15 <= {M3_V49_SHALLOW_RETEST_MAX_ATR15}",
            "threshold_atr15":M3_V49_SHALLOW_RETEST_MAX_ATR15,
            "origin":"V4.7 diagnostic; V4.8 holdout validated",
        },
        "selection":"immutable V4.5.1 cohort; prospective-only expanding replay since 2026-10-12T04:00Z",
        "legacy_reference":"Prior V4.9 run 38199515493 covered 2026-10-05 onward; pre-freeze rows EXCLUDED from prospective evidence.",
        "research_status":"PROSPECTIVE_SHADOW_REPLAY_ONLY_NO_RETUNING_NO_LIVE_PROMOTION",
        "limitations":"Signals are reconstructed later from historical candles; not captured, timestamped or traded live. Repeated expanding-window replay is not an immutable contemporaneous signal ledger.",
    }

def main():
    m=build_manifest()
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v49_manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,ensure_ascii=False,indent=2)
    gh_output=os.getenv("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output,"a",encoding="utf-8") as f:f.write(f"window_ready={'true' if m['window_ready'] else 'false'}\n")
    print(json.dumps({
        "manifest_id":m["manifest_id"],"manifest_status":m["manifest_status"],
        "period_start":m["period_start"],"period_end":m["period_end"],
        "forward_days":m["forward_days"],"block_count":m["block_count"],
        "freeze_commit":m["research_freeze_commit"],"evidence_class":m["evidence_class"],
        "hypothesis":m["hypothesis"],
    },ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
