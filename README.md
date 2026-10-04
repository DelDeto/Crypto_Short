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
