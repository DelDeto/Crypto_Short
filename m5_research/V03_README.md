# M5 V0.3 — Historical Discovery Outcome Gate

**Research only — NO trades, NO entry advice, NO live signals.**
V0.3 works on the immutable **687-coin / 680-accepted** V0.2 full-market
7-day cohort (`m5-full-20261013-7d`). All 8 exploratory families are
evaluated equally, not just models chosen after looking at past profit.

## Scientific design

- Use the **first 75%** of the original cohort for exploratory discovery.
  The remaining 25% begins at the previously frozen
  `plan.holdout_reserved_start_utc`. The final **8 hours before this
  boundary** are additionally purged from outcome analysis to prevent
  historical return labels from crossing the holdout.
- The older V0.2 report already disclosed aggregate event counts across
  the entire 7 days. Thus its holdout is NOT wholly untouched for every
  exploratory decision; V0.3 simply preserves its **future-return secrecy**.
  Truly independent evidence will require a newly preregistered forward
  cohort, or a genuinely unseen historical period without overlapping dates.
- Read **only prior frozen as-of features**, check SHA256 fingerprints of
  all archived accepted/rejected instruments against the V0.2 merged manifest,
  and refuse mismatched or incomplete market archives.
- At each historical event, use only matched controls selected from the
  **same UTC timestamp**, chosen using then-known turnover and volatility
  in V0.2. Missing 8h future bars invalidate the case or control rather than
  fabricating returns. No replacement controls selected after viewing
  outcomes.
- Measure short-direction **close-to-close percentage** from the LAST
  OBSERVED EVENT CANDLE CLOSE to the close of the subsequent 1h, 2h, 4h
  and 8h windows. This is an *unexecutable reference*, not a short fill.
- All four horizon metrics use one common group of cases with **complete
  continuous 8h candle history**, to avoid horizons being cherry-picked
  from different subsets. Paired edge = virtual case short return minus
  the mean return of as-of matched controls.
- Apply 20bps to case short returns as a **descriptive sensitivity only**.
  No actual commission tier, bid/ask spread, funding, market impact,
  liquidation or slippage is measured.
- V0.2 did not retain high, low or virtual next-bar OPEN. Consequently
  **no true MFE / MAE / stop-loss path / executable PnL is calculated**.
  A separate, explicitly versioned raw OHLCV extension is required.
- Clustering by day and across simultaneous coins causes severe
  non-independence. Seven-day history leaves only ~5.25-day discovery
  time. Therefore V0.3 reports descriptive means and signs, **not
  statistically confirmed edge, win rates, p-values or confidence claims**.
- Eight families and four horizons are multiple comparisons. Before
  any holdout/forward testing, freeze ONE primary metric, candidate-selection
  policy, multiplicity correction, dependency-aware uncertainty method and
  prospective stopping rule. A 14-21-day history window overlapping this
  7-day research is not an independent out-of-sample test.

## CLI / GitHub

```bash
python -m m5_research.v03_selftest
python -m m5_research.v03_discovery --study-id m5-full-20261013-7d
```

GitHub Actions: [M5 V0.3 discovery](../../actions/workflows/m5-v03-discovery.yml).
On `main`, after all offline tests pass, the job writes exactly one
`state/m5_research/studies/m5-full-20261013-7d/discovery/v03_close_only_report.json`
and commits it. Existing reports cannot be silently overwritten.
It never reads or scores the reserved historical holdout outcomes.

**Never mistake a positive descriptive average for a tradable signal.**

## After V0.3

1. Inspect descriptive sample sizes, all 8 event families, control attrition
   and overlap/correlations. Note which conclusions are unavailable.
2. Choose one research hypothesis/primary horizon *without looking into the
   reserved holdout future returns*, then freeze it with a new ID.
3. Acquire higher quality 15m open/high/low/close candles in a separate
   versioned collection for honest executable MFE/MAE simulation.
4. Reserve a genuinely independent calendar period/forward event registry;
   run preregistered validation with multiplicity/cluster safeguards.
5. Only then consider entry/SL/TP research, shadow, and potentially live.

Nothing in V0.3 modifies M2/M3/M4, order execution, schedules or Telegram.
