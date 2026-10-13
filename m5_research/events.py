"""Eight candidate event families, calculated only with closed 15m candles.

This module deliberately computes NO future outcomes, PnL or trade entry.
Multiple family labels for the same coin/time are retained as overlapping
events rather than misrepresented as independent samples.
"""
import numpy as np
import pandas as pd
from .config import EVENTS, WARMUP_BARS
from .data import STEP, _utc

def _bool(s):
    return s.fillna(False).astype(bool)

def features_asof(symbol, frame, btc_frame, research_start):
    """Return one as-of feature row per 15m timestamp and eight event flags.

    A complete regular timestamp grid prevents irregular bars from turning
    prior-N candle windows into misleading time periods. Never backfill OHLCV.
    """
    if frame.empty:
        return pd.DataFrame()
    frame = frame.copy().sort_index()
    if frame.index.tz is None:
        raise ValueError("Candle timestamps must be UTC-aware")
    # Only requested timestamps and earlier data; no interpolation/backfill.
    dates = pd.date_range(frame.index.min(), frame.index.max(), freq="15min", tz="UTC")
    f = frame.reindex(dates)
    btc = btc_frame["close"].reindex(dates) if not btc_frame.empty else pd.Series(index=dates, dtype=float)
    o, h, l, c, a = (f[k].astype(float) for k in ("open", "high", "low", "close", "amount"))
    # Features computed from the current CLOSED bar and earlier only.
    prior_hi20 = h.shift(1).rolling(20, min_periods=20).max()
    prior_lo20 = l.shift(1).rolling(20, min_periods=20).min()
    prior_hi16 = h.shift(1).rolling(16, min_periods=16).max()
    prior_lo16 = l.shift(1).rolling(16, min_periods=16).min()
    med40 = a.shift(1).rolling(40, min_periods=40).median()
    ret4 = (c / c.shift(4) - 1) * 100
    ret16 = (c / c.shift(16) - 1) * 100
    ret24 = (c / c.shift(96) - 1) * 100
    btc_ret4 = (btc / btc.shift(4) - 1) * 100
    rel4 = ret4 - btc_ret4
    prev_runup6 = (c.shift(1) / c.shift(25) - 1) * 100
    close_ref_ma12 = c.shift(1).rolling(12, min_periods=12).mean()
    vol = (c / c.shift(1)).apply(np.log).rolling(96, min_periods=96).std() * np.sqrt(96) * 100
    turnover = a.rolling(96, min_periods=96).sum()
    # All event filters use strictly known data at bar close. Missing candle
    # history does not get silently filled.
    complete = c.notna().rolling(WARMUP_BARS, min_periods=WARMUP_BARS).sum().eq(WARMUP_BARS)
    liquid = turnover >= 100000  # exploratory quality floor, NOT a fixed forward hypothesis
    breakdown = c.lt(prior_lo20 * 0.998)
    break_prev8 = breakdown.shift(1).fillna(False).astype(int).rolling(8, min_periods=1).max().gt(0)
    # Last reference support observed at a historical breakdown, never future.
    broken_support = prior_lo20.where(breakdown).ffill(limit=8).shift(1)
    flags = {
        "E01": breakdown,
        "E02": ret4.le(-2.5) & a.rolling(4, min_periods=4).sum().ge(med40 * 4 * 1.8),
        "E03": h.gt(prior_hi20 * 1.002) & c.lt(prior_hi20) & c.lt(o),
        "E04": prev_runup6.ge(10) & c.lt(close_ref_ma12) & c.lt(o),
        "E05": break_prev8 & h.ge(broken_support * 0.995) & c.lt(broken_support) & c.lt(o),
        "E06": h.gt(prior_hi20) & a.ge(med40 * 3) &
               ((h - np.maximum(o, c)) / h).ge(.004) & c.lt(o),
        "E07": ret4.le(-1.0) & rel4.le(-2.0),
        "E08": ((prior_hi16 - prior_lo16) / c.shift(1)).lt(.035) &
               c.lt(prior_lo16 * .998) & a.ge(med40 * 1.25),
    }
    result = pd.DataFrame(index=f.index)
    result["symbol"] = symbol
    result["close"] = c
    result["return_1h_pct"] = ret4
    result["return_4h_pct"] = ret16
    result["return_24h_pct"] = ret24
    result["btc_return_1h_pct"] = btc_ret4
    result["relative_1h_pp"] = rel4
    result["volatility_24h_pct"] = vol
    result["turnover_24h_usdt"] = turnover
    result["quality_ready"] = complete & liquid & vol.notna() & np.isfinite(vol)
    for key, mask in flags.items():
        result[key] = _bool(mask) & result["quality_ready"]
    # Each family/coin event has a 2-hour non-overlap cooldown. The cooldown is
    # an event dedupe rule; not a claim of independent samples across coins.
    for key in EVENTS:
        values = result[key].to_numpy(dtype=bool).copy()
        latest = -10**9
        for i in np.flatnonzero(values):
            if i - latest < 8:
                values[i] = False
            else:
                latest = i
        result[key] = values
    return result.loc[result.index >= _utc(research_start)].copy()

def discover_events(feature_frames):
    """Event rows and as-of same-UTC matched controls (within this shard ONLY).

    A control candidate cannot itself have the exact same event family,
    and is matched by already-observed volatility and liquidity.
    All matching is prospective-AS-OF, but sharded comparisons are preliminary.
    """
    features = [f for f in feature_frames if not f.empty]
    if not features:
        return [], {}, 0
    joined = pd.concat(features).sort_index(kind="stable")
    times = joined.groupby(level=0, sort=True)
    events, control_pool = [], {}
    counts = {key: 0 for key in EVENTS}
    for ts, cohort in times:
        if len(cohort) < 2:
            pass
        rows = cohort.loc[cohort["quality_ready"]]
        if rows.empty:
            continue
        event_rows = rows.loc[rows[list(EVENTS)].any(axis=1)]
        if event_rows.empty:
            continue
        # Snapshot candidate set now, rather than select retrospectively after
        # observing outcome. Not all shard universes are represented here.
        for _, case in event_rows.iterrows():
            for key in EVENTS:
                if not case[key]:
                    continue
                ctrls = rows.loc[(rows["symbol"] != case["symbol"]) & ~rows[key]]
                scored = []
                for _, control in ctrls.iterrows():
                    if not np.isfinite(control["volatility_24h_pct"]):
                        continue
                    if abs(control["volatility_24h_pct"] - case["volatility_24h_pct"]) > 15:
                        continue
                    q1 = max(float(case["turnover_24h_usdt"]), 1)
                    q2 = max(float(control["turnover_24h_usdt"]), 1)
                    if q1 / q2 > 10 or q2 / q1 > 10:
                        continue
                    distance = (abs(control["volatility_24h_pct"] - case["volatility_24h_pct"])
                                + abs(np.log(q1 / q2)) * 2)
                    scored.append((float(distance), str(control["symbol"])))
                scored.sort(key=lambda x: (x[0], x[1]))
                controls = [sym for _, sym in scored[:3]]
                events.append({
                    "event_id": key,
                    "event_name": EVENTS[key],
                    "symbol": str(case["symbol"]),
                    # Timestamp is when the 15m bar is available, NOT its open.
                    "observed_at_utc": (_utc(ts) + STEP).isoformat(),
                    "last_closed_bar_open_utc": _utc(ts).isoformat(),
                    "asof_close": round(float(case["close"]), 10),
                    "return_1h_pct": round(float(case["return_1h_pct"]), 5),
                    "return_4h_pct": round(float(case["return_4h_pct"]), 5),
                    "volatility_24h_pct": round(float(case["volatility_24h_pct"]), 5),
                    "turnover_24h_usdt": round(float(case["turnover_24h_usdt"]), 2),
                    "control_symbols": controls,
                    "control_count": len(controls),
                    "control_scope": "SAME_SHARD_PRELIMINARY_NOT_ALL_MARKET",
                    "research_only": True,
                })
                counts[key] += 1
    return events, counts, len(joined)
