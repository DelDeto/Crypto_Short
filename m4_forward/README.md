# M4 V0.2.3 — Frozen H3 prospective observational study

This is a new research protocol, **NOT** an entry strategy, ranking bot, trade automation or update to M2/M3.

## What was closed

- M4 H1 failed breakout: no convincing absolute short edge; descriptive 24h mean short -1.491%.
- M4 H2 wait-for-breakdown confirmation: no convincing edge; matched 24h delta +0.013pp with CI crossing zero.
- Both are marked **NOT CONFIRMED**. Older Aug–Oct H1/H2 material stays accessible for diagnostic/reference work but may NOT be used for H3 discovery-validation claims.

## H3: Relative weakness + momentum exhaustion

Starting **2026-10-13 00:00 UTC**, observe every four hours, using only each symbol's latest *completed* 1h bar and matching BTC 1h data:

- Last 18h of the 24h lookback: coin price rose by **at least +10%**.
- Last 6h: coin return is **at most -2%**.
- Coin's 6h return minus BTC's 6h return is **at most -3 percentage points**.
- Last 24 closed 1h MEXC `amount` sum >= **300,000 USDT**.
- Every predictor uses closed prices and historically available `amount` at the signal timestamp.

There are **no other H3 thresholds** and no retuning on future captured outcomes. H3 is distinct from H1/H2 and does not require a sweep, breakout, retest, or lower-high.

For each detected H3 event, matched controls are frozen **at that same observation time**, selected among comparable rising, liquid coins which do not qualify for H3. Calipers: predeclared historical 18h return within 12pp, 24h realized volatility within 12pp; rank by scaled differences plus log 24h turnover distance, retain up to 3. No future price may affect matching.

## Point-in-time recording and audit

- `m4_forward.lock` creates a write-once preregistration record at `state/m4_forward/H3_protocol_lock.json` **before** the forward start. Collection is refused if the stored SHA256 of the rules differs or if the lock was not created before the start.\n- `m4_forward.capture` selects the currently active USDT futures universe **at each run**; 685 symbols is not a hardcoded number.
- Does NOT use today's coin list to reconstruct historical populations. Coverage, missing histories, API failures and eligible symbols are recorded.
- Snapshot records only as-of variables and *no outcomes*; it is committed to `state/m4_forward/snapshots/m4-h3-YYYYMMDDTHHZ.json`. Each path is **write-once**. No catch-up reconstruction of missed 4h snapshots.
- Signal time is the end of the last completed 1h candle. Capture must finish **before** the prospective reference entry (open of the *next full* hourly candle). Captures that finish late are invalid, not retroactive signals.
- `m4_forward.settle` examines sealed prior snapshots at least **60h after** the original signal, retrieves only historical MEXC candles needed to measure 24h/48h short-side price changes, MFE/MAE and same-entry-clock control changes. Outcomes are stored separately, write-once, in `state/m4_forward/outcomes/`.
- The reference entry is **hypothetical next full 1h candle open**, never a real fill; no execution simulation. All resulting records remain research-only.

The 4-hour collection schedule creates periodic **snapshots**, not continuous 1h market coverage. Signals that happen between snapshots are *not observed* and must not be backfilled retrospectively. Github Actions may run late or be skipped. Explicitly keep the log of missing/invalid runs.

## V0.2.4 operational reliability (does NOT alter the frozen H3 protocol)

- GitHub attempts each canonical 4h capture at **:17**, with a **:47** backup. A completed canonical snapshot is detected **before fetching any market candles**, avoiding duplicate expense and any overwrite. This is best-effort, not an exactly-once delivery guarantee.
- Manual runs outside canonical UTC hours 00/04/08/12/16/20 do NOT register extra samples.
- Captures finishing after the hypothetical entry's start are flagged INVALID, never interpreted as causal signals.
- `python -m m4_forward.health` reports only registry integrity, count of missing slots after two hours of grace, age of the newest valid snapshot and snapshot/outcome-link SHA verification. **It never opens outcome performance metrics.**
- A missing GitHub cron is recorded as a gap; no artificial historical backfill or retuning is permitted. New operational code may be deployed, but `protocol.py` and its registered SHA256 **must not change**.
- After code deployment, verify the latest GitHub Actions job produced a new `state/m4_forward/snapshots/` file and that it was committed to `main`, not merely printed to logs.

## MEXC 510 rate-limit handling (V0.2.4)

The first new H3 capture (2026-10-13 04:00 UTC) was archived as
`INVALID_CAPTURE_EXCLUDED_FROM_PRIMARY`: only **379 of 687**
coins returned complete features (**55.17%**, beneath the frozen 70%
data-validity threshold). **308 requests were rejected with MEXC API
code 510: "Requests are too frequent".** This was transport failure,
not evidence of H3 edge, and the affected snapshot remains immutable.

`m4_forward/provider.py` provides a 0.80-second global spacing
among five worker threads plus exponential backoff and cross-thread
cooldown upon code 510 or HTTP 429/5xx. The collector and
mature-outcome settler use this M4-only transport. It does **not**
alter `m4_forward/protocol.py`, the H3 hypothesis SHA256, controls,
minimum coverage gate, or any previous snapshot.

If a canonical 4h slot is already archived as INVALID, backup/manual
runs will not silently replace that old observation. Fixes are
prospective only. GitHub success does not equal a valid H3 sample:
check the `status` field and stored file at each future slot.

## Frozen sequential evidence gate

**No performance results viewed before 60 calendar days and mature 48h outcomes.** `m4_forward.first_look` enforces this, with no weekly re-selection or repeated peeks.

At 60d, require >=50 matched events, >=20 unique UTC signal days, and >=95% of eligible snapshot batches to have settled. Otherwise **INCONCLUSIVE** and no positive conclusion. A possible single additional look at 120d would require a separate frozen protocol, not arbitrary weekly tuning.

For a **descriptive supportive** result, require ALL:
1. Mean raw short-side 48h outcome with a predeclared 20bps round-trip sensitivity >0;
2. H3 48h paired difference vs same-clock controls >0;
3. UTC-day-clustered descriptive bootstrap 95% lower bound >0;
4. >=60% of UTC signal days have positive paired difference.

Even if all hold: **no live promotion or claim of actual net profit**. Research still needs an independently replicated validation, as well as true historical exchange costs, funding, spread, slippage, stop/TP, liquidation/mark-price and portfolio-risk simulation.

## CLI / workflow

```
python -m m4_forward.selftest
python -m m4_forward.provider_selftest
python -m m4_forward.lock
python -m m4_forward.capture
python -m m4_forward.settle
python -m m4_forward.first_look
python -m m4_forward.health
```

`.github/workflows/m4-v023-forward-collector.yml` runs on an approximately 4h GitHub schedule (GitHub scheduling is best-effort, not guaranteed). It writes the observations and subsequent outcomes to **new files only** under `state/m4_forward`, using GitHub's workflow token, plus per-run artifacts. If the repository disallows GitHub Actions writes, the run will show a failure and no persistent evidence will be claimed.

No Telegram notifications, live orders or changes to M2/M3. **Running workflows is not evidence of profitable trading.**
