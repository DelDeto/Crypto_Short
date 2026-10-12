# M4 V0.2.2 — delayed confirmation H2 event study

**Exploratory only. Not OOS, not a trading strategy, and not live.**

The first M4 H1 failed breakout study (run `38206513291`) contains 893 events and 844 original matched-control events. Its average outright hypothetical 24h short return is negative and V0.2.1 found severe tails. H2 was formulated **after inspecting those data**, therefore running it on the SAME events cannot confirm an independent edge.

## H2, single fixed hypothesis

After an existing H1 failed-breakout 1h candle has closed:
1. For the next **six completed 1h candles**, at every step if price **closes back at/above the original 48h high**, mark `RECLAIMED_BEFORE_CONFIRM`.
2. Otherwise, the **first completed 1h candle closing strictly below the original failed-breakout/sweep candle's low** is H2 confirmation.
3. Only after that close, measure hypothetical 4/12/24/48-hour short-side percentage changes from the following 1h candle's **open**. *Not an actual fill.*
4. If none confirms after six completed bars, mark `NO_CONFIRMATION_6H`. Missing candles, later outcome incompleteness, data changes and request errors are separate statuses, **not failed trades**.

H2 does **not** claim a lower-high pivot or add stop/TP. No optimized lag, thresholds, labels or coin selection.

## Controls

Original V0.2 control-coin identities are fixed at the H1 event timestamp, with no outcome-based selection. We fetch their price histories and *rebase* 4/12/24/48h controls to the **exact H2 confirmation/next-open time** of each corresponding case. Report case count, unmatched cases, control availability and paired differences. Comparing H2 confirmed outcomes to **all** original H1 events has time/selection biases and is presented descriptively, alongside the *same confirmed coins' original H1 outcomes*.

## Implementation

- `prepare` downloads original V0.2 final artifact and verifies 893/844 cases, source manifest, source hashes, frozen symbols and confirmation parameters.
- 8 shards assign all unique event/control symbols by stable SHA256; fetch only read-only MEXC historical 1h candles, segmenting <=700 bars/request. Each case and control is processed independently; all H1 cases must appear exactly once.
- `merge` checks completeness, sample attrition, aligned outcomes, outputs CSV and a plain-language JSON summary.
- `selftest` proves no future candles affect the confirmation trigger, and validates reclaim rejection, no confirmation, missing maturity and altered-source price.

### Limits

Repeated research on the 2026-08-13 to 2026-10-10 dataset is **NOT out-of-sample**; it suffers from surviving-futures universe bias, possible API candle anomalies, dependent signals and no real fills/costs/liquidation. Passing nominal statistics here does **not** license promotion to M4 V0.3 or live trading. A prospective independent sample must be collected first.

Workflow: `.github/workflows/m4-v022-confirmation-study.yml` (manual and on isolated changes only). No schedule or Telegram/live M2/M3 alterations.
