# Crypto Short Scanner

Short-only crypto futures research scanner for finding higher-quality short setups across the MEXC USDT perpetual market.

## V1 logic

The scanner deliberately does **not** short a coin simply because it is falling.

1. Fast-scan the full MEXC USDT perpetual universe on 1H.
2. Score bearish trend, lower-high/lower-low structure, momentum, volatility, volume, liquidity, funding and location.
3. Apply a **short-chase penalty** when price has already dumped too far from EMA20 or recent momentum is extremely negative.
4. Deep-scan the strongest candidates on 4H + 1H.
5. Detect:
   - bearish multi-timeframe structure;
   - supply-zone proximity;
   - upper-liquidity sweep;
   - bearish rejection;
   - breakdown + retest.
6. Build a short plan with Entry, Stop, TP1 = 2R, TP2 = 3R and a 5R runner.
7. Check room to the nearest swing support before marking a setup actionable.

## Status

- **ENTRY_READY**: score >= 80, bearish 4H/1H alignment, a valid trigger, acceptable volatility/location and enough risk-reward room.
- **DEVELOPING**: score >= 70 with the main bearish structure present, but the setup is not yet ready enough to execute.
- **WATCH**: score >= 60; useful context, not an entry.
- **IGNORE**: insufficient short edge.

Thresholds are configurable in `short_algo/config.py` or through environment variables.

## Run

```bash
pip install -r requirements.txt
python -m short_algo.main
```

Outputs:

- `output/short_scan.json` — full machine-readable report and score breakdown.
- `output/short_scan.csv` — compact table for review/backtesting.
- `output/short_scan.md` — human-readable shortlist.

## GitHub Actions

Use **Actions → Crypto Short Scanner V1 → Run workflow**.

V1 is intentionally manual while the scoring logic is validated. Automated scheduling and Telegram delivery should be enabled only after enough signal outcomes have been audited.

## Risk note

This project is a research/ranking system, not an auto-execution bot. Crypto perpetual futures are highly volatile and leveraged positions can lose more quickly than spot positions.


## V2 — Backtest & calibration

V2 keeps the live V1 scanner intact and adds a research layer to validate whether the rules have measurable historical edge.

### Exclusive setup models

- **TREND_CONTINUATION** — bearish 4H/1H structure plus breakdown/retest.
- **LIQUIDITY_REVERSAL** — prior upside move plus buy-side liquidity sweep and bearish failure/rejection. A top gainer is only hunting context; the sweep/failure is the trigger.
- **SUPPLY_FADE** — rally into 1H/4H supply followed by rejection/lower-high behavior.

### Backtest methodology

- Historical 1H replay with only candles closed at the signal timestamp.
- 4H candles must be fully closed before they are visible to a 1H signal.
- Primary outcome: **+2R before -1R**.
- Same-candle TP1 + SL is conservatively counted as a loss because OHLC cannot reveal intrabar ordering.
- Default horizon: 72 hours.
- Duplicate signals from the same model/symbol are throttled by a cooldown.
- Today's funding, spread and turnover are **not** inserted into historical signal scoring.
- Current turnover can be used only to choose a manageable research sample; this creates selection bias and is explicitly reported.

### Calibration outputs

V2 reports:

- win rate;
- expectancy in R;
- profit factor;
- MAE / MFE;
- sequential max drawdown;
- longest loss streak;
- breakdown by setup model;
- breakdown by score bin;
- KEEP / PROMOTE / DEMOTE suggestions only after enough resolved samples.

Calibration does **not** automatically modify live V1 weights.

### Run V2

Use **Actions → Crypto Short V2 Backtest → Run workflow**.

Recommended first validation:

- 90 days
- 80 symbols
- 72-hour outcome horizon

For a broader robustness check, repeat with 180 days and explicit symbol cohorts rather than relying only on today's most-liquid contracts.

Outputs:

- `output/v2_backtest.json`
- `output/v2_trades.csv`
- `output/v2_calibration.json`
- `output/v2_summary.md`


### Parallel execution

V2 backtests use **4 symbol shards** in GitHub Actions.

For the recommended 90-day / 80-symbol run:

- shard 0: approximately 20 symbols
- shard 1: approximately 20 symbols
- shard 2: approximately 20 symbols
- shard 3: approximately 20 symbols
- final merge job: combines all trades, recalculates calibration, expectancy, profit factor, MAE/MFE and drawdown on the complete sample

Sharding is performed by symbol rather than by time. This preserves each symbol's warm-up history and the full forward outcome horizon around every signal.

Each shard uploads an intermediate artifact. The merged result is published as:

`Crypto-Short-V2-Backtest-Final`

The merge step requires all expected shard indexes, so an incomplete run cannot silently produce a misleading "final" report.


## V2.1 — Model-specific execution

V2.1 is a research upgrade based on the 90-day V2 findings. It does not
automatically replace the live V1 Telegram gate.

### What changed

- **Liquidity Reversal gets its own ENTRY_READY gate.** It no longer requires a
  fully bearish 4H+1H regime. It requires a buy-side sweep, positive 24h context,
  reversal confirmation, acceptable location, volatility and risk.
- **Trend Continuation and Supply Fade are research-only WATCH setups** until
  they show positive out-of-sample expectancy.
- **Complete forward horizon:** signals inside the final outcome horizon are
  excluded, so every tested signal has the full future window available.
- **Terminal exit:** if neither +2R nor -1R is hit, the position closes at the
  final horizon close rather than being discarded as unresolved.
- **Execution costs:** configurable round-trip fee and slippage assumptions are
  deducted from realized R.
- **Baseline challenge:** a simple Bollinger failed-extension mean-reversion
  Short runs beside the complex logic. The complex model should outperform this
  baseline before promotion.
- Reports compare **V1 ENTRY_READY**, **V2.1 ENTRY_READY**, all Liquidity
  Reversals, top-gainer Liquidity Reversals and the Bollinger baseline.

Default research cost assumptions are 8 bps round-trip fees plus 6 bps
round-trip slippage. They are configurable workflow inputs and are not claims
about any specific exchange fee tier.


## V2.2 — Ranked liquidity reversal

V2.2 is the next research layer after V2.1. It remains isolated from the live
V1 Telegram execution gate until historical validation is complete.

### V2.2 architecture

- **4H / 1H context** remains the macro setup layer.
- **15m confirmation** is used for timing and a tighter research stop.
- A dedicated **V2.2 Reversal Score** replaces the old assumption that a higher
  global bearish score is automatically a better reversal setup.
- The reversal score includes:
  - 24h pump magnitude;
  - ATR extension from EMA20;
  - Bollinger z-score / failed upper-band extension;
  - rolling VWAP extension;
  - buy-side liquidity sweep and supply proximity;
  - 1H bearish exhaustion / rejection / volume expansion;
  - 15m lower-high, lower-low, breakdown and rejection confirmation;
  - timestamp-aligned BTC risk-on / neutral-bearish regime.
- V2.2 uses a separate 15m execution plan with +2R TP1, +3R TP2 and a 5R
  research runner.
- Whole-market ranking happens **after all shards merge**, so signals from
  different shards are compared against one another before portfolio selection.
- Default portfolio constraints:
  - top 3 setups per timestamp;
  - max 3 concurrent positions;
  - 0.5% equity risk per ranked trade;
  - starting research equity 10,000.
- A walk-forward threshold report uses a default 60-day training window and
  30-day test window to test whether the score threshold remains useful over
  time.
- V2.1 and the Bollinger mean-reversion baseline remain in the report for
  apples-to-apples comparison.

### V2.2 workflow controls

Manual workflow inputs include:

- historical days;
- symbol limit;
- outcome horizon;
- round-trip fee assumption;
- round-trip slippage assumption;
- V2.2 ENTRY_READY score threshold;
- max concurrent positions;
- portfolio risk percent per trade.

The merged artifact is:

`Crypto-Short-V22-Backtest-Final`

V2.2 should not replace the live scanner solely because one in-sample run is
positive. Promotion should require a materially positive expectancy after costs,
a reasonable profit factor and drawdown, sufficient sample size, and positive
walk-forward behavior.


## V2.2.1 — Crypto-only validation

V2.2.1 is a validation release, not a new trading strategy. The V2.2 entry
logic, 15m confirmation, stop/target rules, BTC regime filter and execution
cost assumptions remain unchanged.

The validation changes are methodological:

- restrict the MEXC derivatives cohort to crypto contracts only;
- exclude equity indices, ETFs, stock synthetics, commodity synthetics and
  commodity-backed gold tokens from the research cohort;
- record an audit list of excluded non-crypto contracts in every final report;
- keep all V2.2 hard gates fixed during walk-forward validation;
- allow walk-forward to tune only the V2.2 score threshold;
- use 60-day train / 30-day test windows by default;
- validate on a broader recommended cohort of 180 days × 150 crypto contracts.

The goal is to determine whether the positive V2.2 result survives a cleaner,
larger and time-separated sample before any live promotion.


## V3 — Multi-Strategy Short Engine

V3 is a clean research architecture rather than an incremental V2 score tweak.
It remains separate from the live V1 scanner until historical validation is
strong enough to justify promotion.

### Market Router

V3 uses timestamp-aligned BTC and ETH 1H context to classify the market as:

- **RISK_ON**
- **NEUTRAL**
- **RISK_OFF**

Each Short engine has its own regime permissions. An extreme pump reversal can
still qualify during strong markets only when its own confirmation is strong;
trend-continuation Shorts require a genuine risk-off environment.

### Five independent Short engines

1. **EXTREME_PUMP_REVERSAL**
   - strong 24h pump;
   - ATR/Bollinger/VWAP extension;
   - buy-side liquidity sweep;
   - 15m failed reclaim and bearish micro structure.

2. **EXHAUSTION_REVERSAL**
   - moderate upside move;
   - multi-factor exhaustion from rejection, failed Bollinger extension,
     volume expansion and VWAP extension;
   - 15m failed reclaim.

3. **BREAKDOWN_RETEST**
   - risk-off BTC/ETH environment;
   - bearish 4H/1H structure;
   - 1H breakdown plus retest;
   - 15m bearish confirmation.

4. **RELATIVE_WEAKNESS**
   - coin underperforms BTC/ETH on 4h and 24h;
   - bearish local structure;
   - avoids chasing assets that have already collapsed too far.

5. **FAILED_BREAKOUT_SUPPLY_FADE**
   - fresh failed breakout / buy-side sweep;
   - supply or failed Bollinger extension location;
   - 15m failed reclaim;
   - excludes extreme-pump context so it does not duplicate Engine A.

### V3 execution gates

Before ENTRY_READY, V3 requires:

- model-specific hard gate;
- max stop percent;
- minimum support room;
- projected execution cost below the configured R budget.

The default cost cap is **0.10R** using the same fee + slippage assumptions as
the backtest. A setup with an attractive chart but a stop so tight that costs
consume too much of its R is rejected.

### Portfolio layer

After all shards merge, V3:

- chooses one primary engine per symbol/timestamp;
- ranks by model score adjusted for execution cost;
- selects at most 3 setups per timestamp;
- limits total concurrent positions;
- limits known correlated clusters such as meme, AI, L1 and DeFi;
- simulates a default 0.5% equity risk per trade.

### Validation

The default manual V3 backtest is:

- 360 days;
- 120 liquid crypto contracts;
- 72-hour outcome horizon;
- 8 parallel shards.

The report separates net-profitable rate from TP-before-SL rate and includes
engine, regime, score/cost behavior, portfolio drawdown and temporal robustness.
The older half of a 360-day run is treated as a retrospective holdout because
the V3 rules were inspired by findings from the more recent V2.2.1 period.

Historical OI/funding is intentionally disabled until timestamp-correct data is
available. V3 does not substitute current OI/funding into historical signals.
