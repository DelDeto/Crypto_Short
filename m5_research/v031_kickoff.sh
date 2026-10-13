#!/usr/bin/env bash
# M5 V0.3.1: once-only frozen 14-day full-market historical discovery cohort.
# Re-running resumes existing checkpoints. No forward evidence or trading.
set -euo pipefail

STUDY_ID="${M5_STUDY_ID:-m5-full-20261013-14d}"
DAYS=14
SHARDS=16
ROOT="state/m5_research/studies"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

persist() {
  git add "state/m5_research/studies/$STUDY_ID"
  if git diff --cached --quiet; then return 0; fi
  git commit -m "research(m5): append immutable 14d discovery checkpoint [skip ci]"
  local success=false
  for attempt in 1 2 3; do
    git pull --rebase origin main
    if git push origin HEAD:main; then
      success=true
      break
    fi
    echo "Checkpoint push conflict, retry $attempt"
  done
  if [ "$success" != true ]; then
    echo "M5 CHECKPOINT NOT PERSISTED; do not claim collected data is safe" >&2
    exit 1
  fi
}

if [ ! -f "$ROOT/$STUDY_ID/plan.json" ]; then
  echo "FREEZE NEW 14-day full-market cohort: $STUDY_ID"
  python -m m5_research.v02 plan --study-id "$STUDY_ID" --days "$DAYS" --shards "$SHARDS"
  persist
else
  echo "RESUME frozen cohort without changing original symbol/time boundaries: $STUDY_ID"
fi

for shard in $(seq 0 15); do
  echo "=== M5 V0.3.1 shard $shard / 15 ==="
  ready=false
  for chunk in $(seq 1 16); do
    if python -m m5_research.v02 status --study-id "$STUDY_ID" --shard-index "$shard"; then
      ready=true
      break
    fi
    python -m m5_research.v02 shard --study-id "$STUDY_ID" \
      --shard-index "$shard" --max-new 5 || true
    persist
  done
  if [ "$ready" != true ]; then
    if python -m m5_research.v02 status --study-id "$STUDY_ID" --shard-index "$shard"; then
      ready=true
    fi
  fi
  if [ "$ready" != true ]; then
    echo "M5 V0.3.1 PARTIAL: shard $shard still has pending instruments" >&2
    echo "Rerun the SAME workflow, never create a replacement time window." >&2
    exit 2
  fi
done

if [ ! -f "$ROOT/$STUDY_ID/merged/research_manifest.json" ]; then
  python -m m5_research.v02 merge --study-id "$STUDY_ID"
  persist
else
  echo "All-market registry already merged: no overwrite"
fi

if [ ! -f "$ROOT/$STUDY_ID/discovery/v031_daily_stability.json" ]; then
  python -m m5_research.v031 --study-id "$STUDY_ID"
  persist
else
  echo "Immutable V0.3.1 day-stability report already archived"
fi

echo "M5_V031_14D_HISTORICAL_DISCOVERY_COMPLETE: $STUDY_ID"
