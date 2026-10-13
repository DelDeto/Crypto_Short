# M5 V0.2 — Frozen Whole-Market Historical Registry

M5 V0.2 is **research-only**. It never computes performance, future outcome
labels, rankings, entry/SL/TP or places orders. Existing M2/M3/M4 models are
untouched. See [V0.1](README.md) for eight candidate detector definitions.

## Important limits

**All-market means all currently listed supported MEXC USDT crypto perpetual
contracts as snapshotted when the study plan is created.** This is NOT all
historically traded/delisted coins. Delisted contracts and any symbols with
insufficient 15m candles are explicitly missing or excluded; their omission
can create survivorship/coverage bias.

The versioned GitHub archive stores compressed **closed-bar as-of research
features** by symbol, not durable raw OHLCV, and not an unlimited data lake.
For operational safety the current Git-backed plan is limited to **1–21 days**.
A **180–240 day / entire market** archive requires object storage (e.g.
Supabase Storage/S3) and a storage quota/cost design. Do NOT use a 240-day
run with Git-backed storage.

## Frozen workflow: plan -> shard checkpoints -> merge

M5 research uses [GitHub Actions V0.2](../../actions/workflows/m5-v02-research.yml).

**Step 1 — PILOT** (automatically also tested on a main code push)

- Choose `mode=pilot`.
- Safely inspects 5 real futures contracts for 2 historical days,
  creates a temporary subset plan and merges it with a clear PILOT status.
- Does NOT commit the pilot data to the repository; stores an Action artifact
  for 30 days and has no auto short suggestions.

**Step 2 — PLAN** (manual launch, intended once per cohort)

- Choose `mode=plan`, e.g. `days=7`, `shards=16`.
- Freeze current real MEXC live contract catalogue, its SHA256, study end
  timestamp, earliest available fully closed 15m bar, preliminary 75/25
  chronological discovery/holdout split, and deterministic hash-shard routing.
- An immutable `state/m5_research/studies/<study_id>/plan.json` is committed.
- Copy the **study_id** from job output for the next steps. Running PLAN a
  second time at a new timestamp starts a distinct study; it must not
  retroactively update the old plan.

**Step 3 — SHARD** (repeat for each 0..15)

- Choose `mode=shard`, `study_id=<existing_id>`, `shard_index=0`.
- Each iteration fetches up to 5 pending symbols. Accepted symbols create
  `shards/shard-XX/features/SYMBOL.csv.gz`; unsupported/insufficient
  historical data create an explicit `shards/shard-XX/rejected/SYMBOL.json`.
- BTC reference OHLCV is cached once per study under
  `context/BTC_USDT.csv.gz`; it is not a proof of entire-market historical
  coverage. 15m candles are required to be CLOSED. Missing candles are
  NEVER filled forward.
- Commits and pushes every five symbols before proceeding, so an interrupted
  job can be restarted without re-fetching its committed work.
- Rate limits MEXC API traffic and retries code 510. Failed transient calls
  are left pending; the shard is NOT misreported as finished.
- One shard at a time avoids concurrent MEXC overload and main-branch
  checkpoint merge conflicts. The workflow serialization lock ensures this.

**Step 4 — MERGE** (manual, only when ALL shards complete)

- Choose `mode=merge`, `study_id=<existing_id>`.
- Inspects and SHA256-fingerprints every frozen member, verifies each symbol
  was either accepted or explicitly rejected, and refuses any missing shard.
- Reconstructs same-UTC feature populations across all shards. Finds each
  event's controls **across all eligible coins in the frozen study**, with
  volatility and liquidity calipers evaluated ONLY from as-of past data.
- Stores `merged/market_events.jsonl.gz` and
  `merged/research_manifest.json` permanently in the repository.
- Immutable registry: never overwrite a merged study. To change detector
  rules, create a NEW version/plan and new untouched holdout.
- Results are frequencies, data quality and **control assignments only**,
  not evidence of profitability.

## Why V0.2 does not calculate win rate yet

The eight event families remain *exploratory*, tested on common historical
conditions; observing raw event frequencies is not statistically independent
evidence. V0.3 will design a hypothesis development/untouched chronological
holdout gate, handle multiple testing and correlate market-wide events.
Only after the hypotheses are explicitly registered should any future return
metrics be examined. Forward testing remains a separate gate.

## Operational checks and cost cautions

- **GitHub Actions success != market scan success.** Check `accepted`,
  `excluded`, `pending` from each shard and the final merge status.
- File commits are permanent Git history. Monitor repo size and retention.
  GitHub is suitable here for **bounded, compact feature studies**, not raw
  180–240 day futures OHLCV at full-market scale.
- MEXC returning HTTP-200 `code=510` can delay collection; do not launch
  16 shards in parallel.
- API limits and GitHub Actions minute limits may change. No automated
  15-minute scanner is enabled by V0.2.
- No automatic backfill of instruments that MEXC has delisted.

### Local offline checks

```bash
pip install -r requirements.txt
python -m m5_research.selftest
python -m m5_research.v02_selftest
```

### Typical CLI

```bash
python -m m5_research.v02 plan --days 7 --shards 16
python -m m5_research.v02 status --study-id <ID> --shard-index 0
python -m m5_research.v02 shard --study-id <ID> --shard-index 0 --max-new 5
python -m m5_research.v02 merge --study-id <ID>
```

Do not run the CLI example literally with `<ID>`; use the frozen plan id
printed after PLAN mode.
