#!/usr/bin/env bash
# Exactly one bounded, exploratory 14-day as-of execution path study.
# Persist frozen selection plan BEFORE requesting outcome high/low bars.
# Never touch another model, send signals or place orders.
set -euo pipefail
EXECUTION_ID="m5-v04-20261013-14d"
ROOT="state/m5_research/execution/$EXECUTION_ID"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

persist() {
  git add "state/m5_research/execution/$EXECUTION_ID"
  if git diff --cached --quiet; then return 0; fi
  git commit -m "research(m5): checkpoint pre-frozen OHLC execution-path pilot [skip ci]"
  local success=false
  for i in 1 2 3; do
    git pull --rebase origin main
    if git push origin HEAD:main; then
      success=true
      break
    fi
    echo "M5 V0.4 archival push retry $i"
  done
  if [ "$success" != true ]; then
    echo "M5 V0.4 ERROR: cannot confirm durable checkpoint" >&2
    exit 1
  fi
}

if [ ! -f "$ROOT/plan.json" ]; then
  python -m m5_research.v04_plan
  persist
else
  echo "M5 V0.4 as-of selection already sealed, no reselection"
fi

ready=false
for chunk in $(seq 1 32); do
  if python -m m5_research.v04_run status; then
    ready=true
    break
  fi
  python -m m5_research.v04_run collect --max-new 8 || true
  persist
done
if [ "$ready" != true ]; then
  if python -m m5_research.v04_run status; then
    ready=true
  fi
fi
if [ "$ready" != true ]; then
  echo "M5 V0.4 partial, preserve plan and resume same cohort later" >&2
  exit 2
fi

if [ ! -f "$ROOT/risk/v04_risk_report.json" ]; then
  python -m m5_research.v04_run summarize
  persist
else
  echo "Already filed risk report; no overwrite"
fi
echo "M5_V04_EXPLORATORY_OHLC_RISK_COMPLETE"
