# M5 V0.4.1 — Entry Timing, Slippage & Outlier Robustness

**Research only.** This is a sensitivity reanalysis of the SAME 48 historical
events already examined in M5 V0.4, using 124 previously archived MEXC
OHLC symbols. It is **NOT an independent holdout, not forward testing, not
live entry recommendations**, and does not submit orders or modify M2/M3/M4.

## Frozen source and immutable audit

Source plan: `state/m5_research/execution/m5-v04-20261013-14d/plan.json`.
The source OHLC files and original risk report are SHA256 cross-checked:
if even one archived file changes, the analysis refuses to run. Both the
original V0.4 report and the new V0.4.1 report remain immutable.

Output (once-only):
`.../risk/v041_entry_robustness.json`
plus `.../risk/v041_event_sensitivity.jsonl.gz`.

No MEXC API or other data service calls are required for this version.

## Entry timing: **same exit clock**, NOT identical holding periods

The event candle opens at T, closes at T+15m, and is not known until then.

- Immediate short hypothetical fill = `OPEN(T+15m)`.
- Delayed one full 15m candle = `OPEN(T+30m)`. This removes the chance to
  capture price moves in the first candle after the signal.
- BOTH positions exit at `CLOSE(bar opening at T+H)` for fixed
  H = 1h, 2h, 4h, 8h event-time windows, so delayed entry holds
  **15 minutes fewer**. This deliberate same-exit-clock comparison uses only
  the originally archived OHLC and must not be misinterpreted as equal
  post-entry holding durations.
- Each OHLC bar must be present; no forward-fill. The signal candle high/low
  cannot enter MFE/MAE. Historical held-out future candles are never fetched.

## Execution sensitivity assumptions

Five basis points fee per side (`5bps entry + 5bps exit`) is charged
using executed notionals. Adverse hypothetical slippage is varied across
`0, 5, 10, 20bps PER SIDE`:
- Short SELL entry receives **lower** price than next-bar-open reference.
- Short COVER exit pays **higher** price than simulated exit reference.
- Short SL and TP barriers are recalculated from the worse **executed entry**,
  so slippage may change the exit reason.
- If one 15m bar hits both SL and TP, assume **SL FIRST**.
- If the market opens above the stop, use the worse open as exit reference.
- Fixed prespecified stop/target sensitivity values: SL1%/TP2%,
  SL1.5%/TP3%, SL2%/TP4%.

**These are scenarios, NOT observed fee tiers, actual spreads, order-book
slippage, funding, market impact or latency.** Stop/fill tick ordering and
liquidation risk remain unresolved. The additive V0.4 cost stress
20/40bps is not interchangeable with this bid/offer execution model.

## What the report measures

For all E01–E08 and 1h/2h/4h/8h horizons:

- Gross short close return and matched-control edge for both entry timings.
- Fee/slippage-stressed net return and paired net edge.
- Fixed SL/TP exit sensitivity after fees and slippage.
- Change in gross return when entry is delayed 15m.
- Median vs mean, trimmed-one-each-side mean, largest outlier, number
  of gross/edge values over 10 percentage points.
- Leave-one-event-out and leave-one-day-out min/max mean edge and
  positive-day count. These are **descriptive stability checks only**;
  six events per family cannot support reliable p-values.

## Workflow

[GitHub Action: M5 V0.4.1](../../actions/workflows/m5-v041-robustness.yml)

A code push runs offline tests on the feature branch. Once tested, the
workflow runs on main to generate this one-time report. If it already exists,
the job skips recomputing it. Outputs are committed with no overwrite.

## Scientific stop gate

Do not compare 8 event families x 4 horizons x 2 timings x 4 slip levels x
3 SL/TP choices and claim the best combination has edge. Those are many
non-independent comparisons on repeatedly seen data.

Before any signal promotion: choose one primary hypothesis, entry clock,
horizon, fees/slippage model, invalidation condition and statistical stop
rules **before** observing a genuinely unseen forward interval; preserve
independent outcome ledger and days/regimes, and investigate survivorship
and liquidity biases. No M2/M3/M4 integration is permitted at this stage.
