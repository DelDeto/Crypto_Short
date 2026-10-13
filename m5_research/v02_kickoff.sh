#!/usr/bin/env bash
# First bounded full-MEXC 7-day event research cohort.
# Checkpoint every 5 instruments to git main, resume safely from durable state.
set -euo pipefail

STUDY_ID="${M5_STUDY_ID:-m5-full-20261013-7d}"
DAYS=7
SHARDS=16
ROOT="state/m5_research/studies"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

persist() {
  git add state/m5_research
  if git diff --cached --quiet; then return 0; fi
  git commit -m "research(m5): checkpoint bounded whole-market 7d cohort [skip ci]"
  pushed=false
  for attempt in 1 2 3; do
    git pull --rebase origin main
    if git push origin HEAD:main; then
      pushed=true
      break
    fi
    echo "M5 checkpoint push conflict, retry $attempt"
  done
  if [ "$pushed" != true ]; then
    echo "FAILED_TO_PERSIST_M5_CHECKPOINT" >&2
    exit 1
  fi
}

if [ ! -f "$ROOT/$STUDY_ID/plan.json" ]; then
  echo "CREATING frozen seven-day all-market M5 plan: $STUDY_ID"
  python -m m5_research.v02 plan --study-id "$STUDY_ID" --days "$DAYS" --shards "$SHARDS"
  persist
else
  echo "RESUMING existing frozen plan, no new catalogue or time window: $STUDY_ID"
fi

for i in $(seq 0 15); do
  echo "==== M5 full market shard $i / 15 ===="
  ready=false
  for chunk in $(seq 1 16); do
    if python -m m5_research.v02 status --study-id "$STUDY_ID" --shard-index "$i"; then
      ready=true
      break
    fi
    # A transport error leaves the symbol pending, not falsely rejected.
    # Persist other accepted members even if one API request failed.
    python -m m5_research.v02 shard --study-id "$STUDY_ID" \
      --shard-index "$i" --max-new 5 || true
    persist
  done
  if [ "$ready" != true ]; then
    if python -m m5_research.v02 status --study-id "$STUDY_ID" --shard-index "$i"; then
      ready=true
    fi
  fi
  if [ "$ready" != true ]; then
    echo "M5_PARTIAL: shard $i remains pending. Rerun workflow to resume." >&2
    exit 2
  fi
done

if [ -f "$ROOT/$STUDY_ID/merged/research_manifest.json" ]; then
  echo "M5 full-market merge already sealed: $STUDY_ID"
else
  python -m m5_research.v02 merge --study-id "$STUDY_ID"
  persist
fi
echo "M5_FULL_MARKET_7D_COMPLETE: $STUDY_ID"
