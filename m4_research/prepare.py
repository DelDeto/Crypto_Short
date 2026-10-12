"""Freeze entire currently-listed MEXC USDT crypto perpetual universe and a research window."""
import hashlib,json,os
from datetime import datetime,timedelta,timezone
from .config import (
    HISTORY_DAYS,WARMUP_HOURS,SHARD_COUNT,MAX_SYMBOLS,OUT_DIR,
    HORIZONS_HOURS,RUNUP_24H_MIN_PCT,SWEEP_MIN_PCT,WICK_MIN_RATIO,
    PREVIOUS_HIGH_HOURS,MIN_ASOF_QUOTE_TURNOVER_24H,
    SAME_SYMBOL_COOLDOWN_HOURS,MATCHED_CONTROLS_PER_EVENT,
)
from .market import snapshot_universe

def build_manifest(now=None,snapshot_fn=snapshot_universe):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)
    universe,audit=snapshot_fn()
    if len(universe)<10:raise RuntimeError(f"Too few live USDT crypto futures: {len(universe)}")
    universe=sorted(set(universe))
    if MAX_SYMBOLS>0:universe=universe[:MAX_SYMBOLS]
    signal_start=now-timedelta(days=HISTORY_DAYS)
    fetch_start=signal_start-timedelta(hours=WARMUP_HOURS)
    last_closed_open=now-timedelta(hours=1)
    signal_end=now-timedelta(hours=max(HORIZONS_HOURS))
    if signal_end<=signal_start:raise RuntimeError("History window too short for outcomes")
    identifier={
        "universe":universe,"snapshot_utc":now.isoformat(),
        "signal_start":signal_start.isoformat(),"signal_end":signal_end.isoformat(),
        "rules":[RUNUP_24H_MIN_PCT,SWEEP_MIN_PCT,WICK_MIN_RATIO,PREVIOUS_HIGH_HOURS,
                 MIN_ASOF_QUOTE_TURNOVER_24H,SAME_SYMBOL_COOLDOWN_HOURS],
    }
    digest=hashlib.sha256(json.dumps(identifier,sort_keys=True).encode()).hexdigest()[:16]
    return {
        "version":"M4-V0.1-V0.2","manifest_id":"m4event-"+digest,
        "snapshot_utc":now.isoformat(),"signal_start":signal_start.isoformat(),
        "signal_end_exclusive":signal_end.isoformat(),"fetch_start":fetch_start.isoformat(),
        "last_closed_candle_open":last_closed_open.isoformat(),
        "symbol_count":len(universe),"symbols":universe,"shard_count":SHARD_COUNT,
        "catalogue_audit":audit,
        "universe_selection":"ACTIVE_USDT_CRYPTO_PERPETUALS_AT_CURRENT_SNAPSHOT",
        "survivorship_warning":"Today's listed universe is NOT a historical point-in-time universe. Delisted coins are missing; all 60d results are EXPLORATORY, not OOS.",
        "historical_liquidity_source":"MEXC hourly kline.amount rolling sum over previous 24 closed candles; NEVER current ticker",
        "event_rule":{
            "runup_24h_min_pct":RUNUP_24H_MIN_PCT,"sweep_min_pct":SWEEP_MIN_PCT,
            "upper_wick_min_ratio":WICK_MIN_RATIO,"previous_high_hours":PREVIOUS_HIGH_HOURS,
            "bearish_candle_required":True,
            "min_asof_quote_turnover_24h":MIN_ASOF_QUOTE_TURNOVER_24H,
            "same_symbol_cooldown_hours":SAME_SYMBOL_COOLDOWN_HOURS,
        },
        "horizons_hours":list(HORIZONS_HOURS),
        "matched_controls_per_event":MATCHED_CONTROLS_PER_EVENT,
        "research_only":True,"no_live_short_signals":True,
        "max_symbols_debug":MAX_SYMBOLS,
    }

def main():
    m=build_manifest()
    os.makedirs(OUT_DIR,exist_ok=True)
    with open(os.path.join(OUT_DIR,"manifest.json"),"w",encoding="utf-8") as f:json.dump(m,f,indent=2,ensure_ascii=False)
    print(json.dumps({k:m[k] for k in ("manifest_id","snapshot_utc","symbol_count","signal_start","signal_end_exclusive","survivorship_warning")},indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
