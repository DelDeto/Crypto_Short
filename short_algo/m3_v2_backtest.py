"""M3 V2 60d replay."""
import json
import os
import pandas as pd

from .config import BACKTEST_SHARD_COUNT, BACKTEST_SHARD_INDEX, BACKTEST_WARMUP_DAYS
from .indicators import return_pct
from .m3_v2_config import M3_V2_COOLDOWN_HOURS
from .m3_v2_execution import evaluate_m3_v2
from .mexc import fetch_backtest_frames, get_klines_window


def _load_manifest(path=None):
    path = path or os.getenv("M3_V2_MANIFEST_PATH", "frozen/m3_v2_manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_shard(symbols):
    return [s for i, s in enumerate(symbols) if i % int(BACKTEST_SHARD_COUNT) == int(BACKTEST_SHARD_INDEX)]


def _closed(frame, signal_time, hours):
    if frame is None or frame.empty:
        return None
    return frame.loc[(frame.index + pd.Timedelta(hours=hours)) <= pd.Timestamp(signal_time)]


def _market_context(btc_one, eth_one, signal_time):
    btc = _closed(btc_one, signal_time, 1)
    eth = _closed(eth_one, signal_time, 1)
    if btc is None or eth is None or len(btc) < 30 or len(eth) < 30:
        return {"m3v2_market_state": "UNKNOWN"}
    r4 = (return_pct(btc["close"], 4) + return_pct(eth["close"], 4)) / 2.0
    r24 = (return_pct(btc["close"], 24) + return_pct(eth["close"], 24)) / 2.0
    state = "RISK_ON_STRONG" if r4 >= 1.0 and r24 >= 2.0 else ("RISK_OFF" if r4 <= -0.8 and r24 <= 0 else "NEUTRAL")
    return {"m3v2_market_state": state, "m3v2_market_r4_pct": round(r4,4), "m3v2_market_r24_pct": round(r24,4)}


def _replay_symbol(symbol, frames, period_start, period_end, btc_one, eth_one):
    fifteen, one, four = frames.get("15M"), frames.get("1H"), frames.get("4H")
    if any(x is None or x.empty for x in (fifteen, one, four)):
        return [], {"symbol": symbol, "error": "missing frames"}
    fifteen, one, four = fifteen.sort_index(), one.sort_index(), four.sort_index()
    start, end = pd.Timestamp(period_start), pd.Timestamp(period_end)
    if start.tzinfo is None: start = start.tz_localize("UTC")
    if end.tzinfo is None: end = end.tz_localize("UTC")

    rows, last = [], None
    for pos, ts in enumerate(one.index):
        signal_time = ts + pd.Timedelta(hours=1)
        if not (start <= signal_time <= end) or pos < 100:
            continue
        four_closed = _closed(four, signal_time, 4)
        if four_closed is None or len(four_closed) < 60:
            continue
        result = evaluate_m3_v2(one.iloc[:pos+1], four_closed, fifteen, signal_time)
        if result.get("m3v2_state") != "ENTRY_BENCHMARK":
            continue
        if last is not None and signal_time - last < pd.Timedelta(hours=int(M3_V2_COOLDOWN_HOURS)):
            continue
        last = signal_time
        rows.append({"symbol": symbol, "signal_time": signal_time.isoformat(), **_market_context(btc_one, eth_one, signal_time), **result})
    return rows, None


def run_m3_v2_backtest(manifest_path=None):
    manifest = _load_manifest(manifest_path)
    period_start, period_end, future_end = map(pd.Timestamp, (manifest["period_start"], manifest["period_end"], manifest["future_end"]))
    selected = _apply_shard(manifest["symbols"])
    warmup_start = period_start - pd.Timedelta(days=int(BACKTEST_WARMUP_DAYS))
    errors, contexts = [], {}
    for symbol in ("BTC_USDT","ETH_USDT"):
        try: contexts[symbol] = get_klines_window(symbol, "1h", warmup_start, future_end)
        except Exception as exc:
            contexts[symbol] = None
            errors.append({"symbol":symbol,"error":f"context: {exc}"})

    rows=[]
    for idx,symbol in enumerate(selected,1):
        try:
            frames=fetch_backtest_frames(symbol,period_start,future_end,warmup_days=BACKTEST_WARMUP_DAYS)
            part,err=_replay_symbol(symbol,frames,period_start,period_end,contexts.get("BTC_USDT"),contexts.get("ETH_USDT"))
            rows.extend(part)
            if err: errors.append(err)
        except Exception as exc:
            errors.append({"symbol":symbol,"error":str(exc)})
        print(f"[M3 V2 {int(BACKTEST_SHARD_INDEX)+1}/{int(BACKTEST_SHARD_COUNT)}] [{idx}/{len(selected)}] {symbol}: entries={len(rows)} errors={len(errors)}",flush=True)
    rows.sort(key=lambda r:(str(r.get("signal_time")),str(r.get("symbol"))))
    return {"engine":"M3 V2 Clean 3% Retest Entry","manifest_id":manifest["manifest_id"],"manifest":manifest,"period_start":manifest["period_start"],"period_end":manifest["period_end"],"future_end":manifest["future_end"],"days":manifest["days"],"shard_index":int(BACKTEST_SHARD_INDEX),"shard_count":int(BACKTEST_SHARD_COUNT),"selected_symbols":selected,"selected_symbol_count":len(selected),"entries":rows,"errors":errors}
