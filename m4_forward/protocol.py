"""M4 V0.2.3 frozen registration protocol for NEW H3 research.

Do not retroactively test H3 on Aug-Oct 2026 M4 H1/H2 data.
No adjusting rules after forward collection begins. If changed, increment hypothesis ID.
"""
from datetime import datetime,timezone
import json,hashlib
HYPOTHESIS_ID="M4_H3_RELATIVE_WEAKNESS_MOMENTUM_EXHAUSTION_V1"
FREEZE_START_UTC="2026-10-13T00:00:00+00:00"
CAPTURE_INTERVAL_HOURS=4
ASOF_CANDLES=25 # 24h change + closed candle
PRIOR_18H_MIN_PCT=10.0
LAST_6H_MAX_PCT=-2.0
RELATIVE_LAST_6H_MAX_PP=-3.0
ASOF_24H_MIN_TURNOVER_USDT=300000.0
MIN_CONTROLS_PER_CASE=1
MAX_CONTROLS_PER_CASE=3
HORIZONS_HOURS=(24,48)
EVALUATE_AFTER_HOURS=60 # delayed settled outcomes; 48h labels + safety buffer
MIN_CALENDAR_DAYS_FIRST_LOOK=60
MIN_MATCHED_EVENTS_FIRST_LOOK=50
MIN_UNIQUE_SIGNAL_DAYS_FIRST_LOOK=20
COST_STRESS_ROUND_TRIP_BPS=20 # sensitivity only, NOT exchange's actual tier
RESEARCH_ONLY=True
def rules():
    return {
        "hypothesis_id":HYPOTHESIS_ID,"freeze_start_utc":FREEZE_START_UTC,
        "cadence_hours":CAPTURE_INTERVAL_HOURS,"prior18h_min_pct":PRIOR_18H_MIN_PCT,
        "last6h_max_pct":LAST_6H_MAX_PCT,"relative_last6h_max_pp":RELATIVE_LAST_6H_MAX_PP,
        "min_asof_24h_quote_turnover_usdt":ASOF_24H_MIN_TURNOVER_USDT,
        "horizons_hours":list(HORIZONS_HOURS),"first_evaluation_after_calendar_days":MIN_CALENDAR_DAYS_FIRST_LOOK,
        "first_evaluation_min_matched_events":MIN_MATCHED_EVENTS_FIRST_LOOK,
        "first_evaluation_min_unique_days":MIN_UNIQUE_SIGNAL_DAYS_FIRST_LOOK,
        "benchmark":"same-UTC candidates with runup and liquidity, no H3 flag; frozen at capture",
        "research_only":True,"short_orders_disabled":True,
        "signal_registration":"Close of last fully completed 1h bar, sampled every 4h; no retrospectively inserted H3 signals",
        "forward_entry_reference":"Open of the 1h candle beginning one full hour after signal becomes available; NOT a guaranteed fill",
    }
PROTOCOL_HASH=hashlib.sha256(json.dumps(rules(),sort_keys=True).encode()).hexdigest()
def prospective_started(now):
    now=now or datetime.now(timezone.utc)
    return now>=datetime.fromisoformat(FREEZE_START_UTC)
