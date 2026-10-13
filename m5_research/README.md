# M5 V0.1 — Whole-Market Historical Event Discovery (Research Only)

**This is an exploratory data pipeline, not a trading bot.** It emits no
short recommendations, entry, SL/TP, orders, performance labels, or PnL.
M2/M3/M4 source code and model protocols are untouched.

## Research universe and scale

- MEXC USDT perpetual crypto contracts listed **now**, not a list of top coins.
- Deterministic SHA-256 symbol sharding: to cover the current catalogue run
  each shard index 0 through 15 with `full_shard=true` and `shards=16`.
  These are 16 independent, potentially costly GitHub runs, NOT automated.
- Every selected coin: 15-minute OHLCV + volume/USDT turnover. Hourly and
  four-hour *trailing* returns are computed from 15m candles already closed,
  not from a concurrently forming 1h/4h bar.
- Maximum requested lookback: 240 days, if the MEXC API actually has that
  history. Initial prudent pilot is 7-14 days and 5-12 symbols.
- A 128-bar causal warm-up is fetched before the first research timestamp.
  Missing 15m candles are **never** interpolated.
- A current live catalogue creates survivorship bias in older history:
  missing delisted instruments cannot be retrospectively reconstructed.

## Eight exploratory detectors

- **E01** Support Breakdown: last closed 15m candle breaks preceding 20-bar low.
- **E02** Downside Momentum Expansion: severe 1h return and abnormal turnover.
- **E03** Liquidity Sweep Reversal: spikes above prior 20-bar high, closes below.
- **E04** Overextension Mean Reversion: strong preceding rally, then weakness.
- **E05** Failed Support Reclaim: broken previous support tested and rejected.
- **E06** Volume Climax Reversal: upper wick, new high and high turnover.
- **E07** Relative Weakness vs BTC: loses ground over the latest closed hour.
- **E08** Volatility Compression Breakdown: tight prior range then break down.

These thresholds are first-pass **discovery candidates**. They have not been
frozen as hypotheses for future confirmation, and there is no expectation that
any of the eight have a positive short edge.

For each coin and family, a simple 2-hour cooldown reduces overlapping
repeats. Different families can fire together, and simultaneous coins can be
highly correlated: **event counts are NOT statistically independent samples.**

## Data validity and as-of control selection

1. At least 85% of research-window 15m candles for each included symbol.
   Event features additionally require 128 consecutive nonmissing candles,
   24h of valid turnover and observed price volatility.
2. BTC same-UTC history is required for the relative-weakness event.
3. For any family/event at time T, select up to 3 controls with:
   same UTC T, no event from that same family, comparable observed volatility
   and USDT turnover (limits: 15 volatility points and 10x turnover).
4. **V0.1 control pool is restricted to the current shard.** A full-market
   matched control population and merged study follow in V0.2.
5. Do not compute outcomes or choose event thresholds from historical returns
   during V0.1. Freeze a separate hypothesis and preserve a genuinely untouched
   chronological holdout before studying outcomes.

## Start a pilot on GitHub

[Actions > M5 V0.1 Historical Event Research](../../actions/workflows/m5-v01-research.yml)
→ **Run workflow**, using **main** after merge:

- `days = 14`
- `shards = 16`
- `shard_index = 0`
- `full_shard = false`
- `max_symbols = 12`

This is **only a small pilot**, not whole-market historical coverage.
For full coverage, run each shard independently, set `full_shard=true`,
and consider extending lookback in stages. A 180-day, whole-market crawl can
require thousands of paced API requests and substantial GitHub Actions time.
MEXC API availability and limits are not guaranteed. Do not launch all 16
shards at once until rate-limit and cost behavior has been measured.

Locally:

```bash
pip install -r requirements.txt
python -m m5_research.selftest
python -m m5_research.run --days 14 --shards 16 --shard-index 0 --max-symbols 12
```

Historical run outputs go to `output/m5_research/<UTC-batch>/shard-X-of-Y/`:

- `manifest.json`: full catalogue fingerprint, selected coins, history
  coverage, rejections/API attempts, family counts, control count and caveats.
- `candles/*.csv.gz`: 15m OHLCV for accepted symbols, current run.
- `event_registry.jsonl.gz`: event timestamp, features and as-of controls.

Artifacts are stored for 30 days by GitHub Actions. **They are NOT yet a
permanent cross-run data warehouse.** Before expensive 180-240-day backfills,
design durable object storage and a shard merge/checkpoint stage in V0.2.

## Next research gates

- **V0.2:** Merge all shards by identical historical as-of timestamp, assign
  truly market-wide controls, historical event frequencies and coverage.
- **V0.3:** Select explicit hypotheses and reserve untouched chronological
  holdout; assess outcome horizons and multiple-testing corrections.
- **V0.4:** Preregister selected rules; 14-21-day forward trial, no live
  orders. Extend if observations are too sparse or dependence too high.
- **Later:** Only after independent evidence, model execution, costs, risk,
  and shadow trading. Never auto-promote 8 discoveries to live signals.

Do not mistake healthy data collection, numerous events or any random
historical sample for evidence that shorting these patterns makes money.
