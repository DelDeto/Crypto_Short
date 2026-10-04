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
