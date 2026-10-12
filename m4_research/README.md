# M4 V0.1 + V0.2 — independent short-reversal research

**RESEARCH ONLY: no executable entry, stop, TP, leverage, trade orders, AI recommendations, Telegram bot, or live model promotion.** Separate from M2 and M3.

## H1: failed bullish breakout

At the close of a 1h candle, all of the following have occurred:

- Previous **24h close-to-close return >= +8%**
- Current candle **high > previous 48 closed 1h highs by >=0.25%** (the previous-high window excludes the current bar)
- Current candle **closes below** that previous 48h high and **closes below open**
- Upper wick >=35% of the current candle high–low range
- The last 24 **already-closed 1h candles** show kline `amount` totaling >=USDT 300,000
- Suppress repeated same-symbol events for 48h

These parameters are predeclared exploratory hypotheses, not optimized settings.

At the end of the trigger candle, the model labels what would happen after **the next 1h bar open** for 4h, 12h, 24h, 48h. It reports observed short-side percentage returns and maximum favorable/adverse excursions; these are **not actual fills or portfolio PnL**.

## Research procedure

1. Get all currently listed USDT crypto perpetual contracts from MEXC contract detail. Freeze the symbol list in the manifest **without choosing winners via today's turnover**.
2. Shard all contracts evenly across 8 runners. Read the last 60d of historical 1h candles in <=700-bar API chunks, plus 80h feature warmup. Inspect gaps, amount availability, coverage, and fetch errors. Strictly exclude incomplete 48h future labels.
3. Extract H1 events and an *as-of-time* comparison pool of similar +8% run-up coins. A matched control is another coin at the **same exact UTC signal time** with no H1 trigger; nearest by 24h return, realized volatility, 24h quote turnover (all features observed at signal time). Match up to 3 controls without inspecting outcomes.
4. Report descriptive event/control short returns at 4/12/24/48h; 24h paired mean and day-cluster bootstrap CI; event MFE and MAE; match rate, history coverage and errors.

## Major research limitations — deliberately surfaced

- **Survivorship bias:** Historical events are sampled from contracts still listed today; de-listed coins are absent. 60d study is **exploratory only**, not point-in-time OOS.
- **No cost/execution model:** No historical spread, fees, borrow/funding, slippage, maker/taker queue, 15m execution, TP or SL.
- **No independent untouched sample:** H1, feature thresholds and study scope must be frozen before a future untouched / prospectively captured validation. Favor reporting failures over tuning.
- **Dependence:** Events in the same market selloff are correlated. Control reuse, unmatched signals and a simple UTC-day-cluster bootstrap are disclosed; the CI is not a formal multiple-tests correction.
- **Missing information:** MEXC 1h kline `amount` is used as turnover proxy at the signal time. Symbols missing this field won't be labeled without a valid as-of liquidity check.
- **Coin types:** Inherits only the existing repository's asset-type exclusions, which are not guaranteed to identify every tokenized synthetic.
- **Rate limit / data access:** MEXC supports at most 2,000 kline points per HTTP request; client requests <=700 and checks coverage. Use `M4_MEXC_BASE_URL` to override current API domain when genuinely required.

## Files and commands

- `python -m m4_research.selftest` — offline test; network not needed
- `python -m m4_research.prepare` — freeze current research universe and window; API required
- `M4_MANIFEST_PATH=frozen/m4/manifest.json M4_SHARD_INDEX=0 M4_SHARD_COUNT=8 python -m m4_research.shard` — one shard
- `python -m m4_research.merge m4_shards frozen/m4/manifest.json` — validate completeness, match controls and publish final output

Workflow: `.github/workflows/m4-event-study.yml`. Default `M4_MAX_SYMBOLS=0` means **all** active USDT crypto contracts, not 120; nonzero only for diagnostics, and manifest discloses this.

Artifacts: `manifest.json`, `m4_study.json`, `m4_events.csv`, `m4_matched_controls.csv`, `m4_coverage.csv`, `m4_summary.md`.

**Next gate:** Do not proceed to M4 V0.3 execution or live alerts until H1 has enough matched independent events and results have been reviewed for regime stability, survivorship, leakage and cost sensitivity.
