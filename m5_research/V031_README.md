# M5 V0.3.1 — 14-Day Market-Wide Discovery Stability

**Status:** extended historical **exploration**, not independent validation.
No order execution, no Short recommendations, no SL/TP, no actual fills.

## Scope

- Freeze a NEW, separate 14-day cohort at the time the first run starts:
  `m5-full-20261013-14d`.
- Full current MEXC USDT crypto-perpetual catalogue, SHA256 frozen in
  `plan.json`, grouped into 16 deterministic shards.
- Fetch closed 15m candles. Only compact as-of features and close prices are
  durably committed to GitHub, with 5-symbol checkpoints.
- Allow restarts of the **same** frozen study. Missing API requests retry;
  historical window and symbol universe never shift on resume.
- After all shards complete, merge all eight event families and assign
  same-UTC as-of controls across the frozen available market.
- Preserve 25% chronology as a reserved research holdout, plus an 8h
  outcome embargo before that boundary.
- On the 75% discovery portion, compute hypothetical event-close to
  +1h/+2h/+4h/+8h close-to-close short-direction returns and paired edge.
  **This does not model an executable entry**.
- Produce per-family **calendar-day sample counts, mean paired edges,
  positive-day fractions, and leave-one-day-out sensitivity** for each
  horizon. These are descriptive diagnostics, NOT p-values or valid
  evidence that the strategy beats randomness.

### Methodological limitations

The original 7-day market-wide cohort was **already inspected**. The
14-day window will overlap it. This extended study must NEVER be called
an untouched holdout or independent out-of-sample validation. It also
does not permit winner selection by searching among 8 families x 4
horizons and then claiming confirmation on the same days.

Full OHLC candles and observed transaction data were not kept in V0.2;
therefore MFE/MAE, stops, liquidation, funding, spreads, fees and
slippage remain **unmeasured**. Those require a separate V0.4
collection and risk model. Git-backed history is bounded to 21 days;
a 180-day full-market data warehouse should use object storage
with explicit quotas and deletion/retention policies.

### Workflow

[GitHub Action](../../actions/workflows/m5-v031-14d.yml)

A code push to `main` creates the first scheduled-once kickoff. Rerun
the **same workflow** if it stops part-way through; it resumes the same
`study_id`. Never create a new plan to hide a missing shard.

Data in:
`state/m5_research/studies/m5-full-20261013-14d/`

- `plan.json` — immutable universe/time and boundary.
- `shards/shard-XX/features/` — archived closed-bar historical features.
- `merged/research_manifest.json` — final coverage, exclusion and count audit.
- `merged/market_events.jsonl.gz` — time-causal full-market event registry.
- `discovery/v031_daily_stability.json` — final exploratory outcome stability
  diagnostics, with clear no-independent-validation flag.

### Next gate

V0.4 must acquire full OHLCV and investigate MFE/MAE and fee/funding
sensitivities, then design a **new pre-registered** forward cohort. A
positive historical average is not sufficient to put any of E01–E08
into M2/M3/M4 or live trading.
