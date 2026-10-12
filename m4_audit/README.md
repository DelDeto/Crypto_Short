# M4 V0.2.1: frozen risk & robustness audit

This is a **read-only post-hoc diagnostic**, not an updated short strategy.

Input is pinned to historical GitHub Actions run **38206513291**, artifact `M4-V02-Event-Study-Final`, manifest `m4event-ed877792e8b4f42b`. Its event sample, H1 thresholds and matched controls are never changed.

The workflow downloads ONLY that finished artifact; it does not rescan all 685 contracts, edit M2/M3, place orders or send trade alerts. It verifies original counts, IDs, 24h mean matched edge, forward outcome arithmetic, and unique signal keys.

The audit reports full-sample short-side tail losses, 24h MAE exceedances, worst 5%, case-level outlier flags, daily/weekly distribution, equal-day/equal-symbol weighting, 1%/5% trimming/winsorizing (sensitivity only), a UTC-day clustered descriptive bootstrap, optional BTC 24h **as-of-time** context and read-only MEXC candle rechecks of extreme cases.

**Outliers are not deleted.** Exchange candle reproduction does not certify actual tradeability or valid tick-level prices. Post-hoc slices are not new filters. There is no real execution/SL/TP/funding, untouched OOS validation or elimination of survivorship bias.

Artifacts: `m4_v021_audit.json`, `m4_v021_summary.md`, `m4_v021_extreme_events.csv`, `m4_v021_rechecks.csv`, `m4_v021_daily.csv`, `m4_v021_weekly.csv`, `m4_v021_btc_regime.csv`.

Run after downloading the frozen artifact into `frozen/v02`:

```bash
python -m m4_audit.selftest
python -m m4_audit.audit --check-market
```

**Not eligible for live deployment or V0.3 trading execution.** Future research must pre-register new hypotheses, add untouched prospective data, and simulate trading costs before any promotion.
