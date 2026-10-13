# M5 V0.4 — OHLC Execution and Risk Pilot (Historical, No Orders)

This version measures **short risk exposure after historical events** from
the immutable V0.3.1 discovery registry. It does not issue recommendations
or place orders. Existing M2/M3/M4 and earlier M5 frozen registries are
unchanged.

## Why not simulate all 60,381 event occurrences now?

Before scaling MFE/MAE calculations to hundreds of symbols and thousands of
correlated events, V0.4 tests that event timing, next-bar entry proxies,
15-minute intrabar ambiguity, missing OHLC and checkpoint recovery work
correctly. The initial sample is **deterministic, exploratory and bounded**.

The planning job first freezes up to **six discovery events per family**,
one per UTC day where possible (eight families = at most **48 event
occurrences**), using a predeclared SHA256 selection rule. Two previously
matched same-time as-of controls accompany each event. No future high,
low, next-open, return, outcome or stop result influences event selection.

**All 48 events are NOT independent.** Overlapping event families, symbols,
and common market conditions remain. The 14-day historical sample overlaps
the 7-day period inspected before this version. This is NOT out-of-sample
validation, and the final 25% history holdout remains closed.

## Entry, MFE/MAE and exit definitions

Let `T` be the opening timestamp of a 15-minute event bar that becomes
fully observed at `T + 15m`.

- **Hypothetical entry**: next 15m candle OPEN, at `T + 15m`. Zero
  latency assumed; this is NOT a guaranteed fill.
- **MFE short**: `(entry - MIN(next H-bar LOW))/entry × 100%`.
- **MAE short**: `(MAX(next H-bar HIGH) - entry)/entry × 100%`.
  MFE/MAE use only the candles AFTER the event bar, not the event wick.
- Horizons `H`: **1h, 2h, 4h and 8h**, computed over 4, 8, 16 and
  32 consecutive 15m OHLC candles. If one bar is missing, that case
  (or matched control) is explicitly excluded.
- Hypothetical no-stop close return: `(entry - final close)/entry × 100%`.
  Matched controls get the exact SAME timestamp and next-open proxy.
- Three **preselected** SL/TP cases: **1%/2%**, **1.5%/3%** and
  **2%/4%**. These are SENSITIVITIES, not retrospectively optimized exits.
- If a 15m high crosses SL and low crosses TP, **SL is assumed hit first**.
  Gap opens through a stop use the less favorable OPEN; favorable gaps
  through TP are capped at stated TP. The intrabar order of transactions
  is unknown; there is NO tick data.
- Apply **20bps and 40bps round-trip cost stress** by subtracting 0.2%
  or 0.4% from hypothetical short outcomes. The actual bid/ask spread,
  real exchange fee tier, funding and market impact are not measured.
- Leverage, liquidation, position sizing, exchange order rejection,
  funding time and portfolio capacity are NOT modeled.

## Storage design and safety controls

The code stores a fingerprinted plan BEFORE fetching future OHLC bars:

`state/m5_research/execution/m5-v04-20261013-14d/plan.json`

Read-only 15m OHLC from MEXC is fetched in blocks with request pacing,
retry on HTTP429/MEXC code 510, and saved as compact per-symbol gzip
checkpoints containing only the bars for PRESELECTED event windows:

`.../ohlc/SYMBOL.csv.gz`

Transient failures remain pending, never mistaken for complete coverage.
Checkpoints are Git-committed every eight symbols. No raw OHLC inside the
reserved holdout is stored. The research-only report is sealed at:

`.../risk/v04_risk_report.json`

with per-event path logs at:

`.../risk/v04_event_paths.jsonl.gz`

The report discloses sample counts, discarded events, available MFE,
MAE, price gap, close-return and fixed SL/TP stress, together with same-UTC
paired-control comparisons. The report does not generate a shortlist of
coins to trade live.

## GitHub Actions

[M5 V0.4 OHLC Execution and Risk Pilot](../../actions/workflows/m5-v04-risk.yml)

This workflow tests all V0.1–V0.4 offline invariants, and on main runs
the bounded historical OHLC pilot. Rerun the same workflow only for
failed/incomplete shards. Do not modify the frozen sample and re-run
as if it were an untouched validation.

## Research decisions after V0.4

The result may identify unrealistic stops, large adverse excursions,
lack of executable return or mismatched entry effects. **Never claim
positive edge from 48 sampled events**. Before validating a system:

1. Register new hypotheses, entry/exit parameters and primary horizon
   before observing a fresh time period.
2. Use independent forward or never-viewed holdout data with realistic
   exchange-specific spread, fees, funding, latency and errors.
3. Check day/coin/market-regime clustered uncertainty and control
   stability, and correct for multiple testing.
4. Only then consider larger OHLC research, shadow signals or trading.
