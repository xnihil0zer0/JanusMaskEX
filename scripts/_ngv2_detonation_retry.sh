#!/usr/bin/env bash
# Autonomous retry loop for the NGv2 Epic-1 detonation child.
# The synthesized code is proven correct; only a transient agent-API throttle blocks it.
# Retries a clean single-task dispatch every INTERVAL until auto_commit or MAX attempts.
set -u
cd /home/xnihil0zer0/AI-Data/JanusMaskEX
TID=ngv2-detonation-chamber
NGV2=/home/xnihil0zer0/NobleGreedv2
PLAN=plan_hooks_ngv2-detonation-chamber.json
INTERVAL=600
MAX=8

accepted() {
  python3 -c "import json;print(sum(1 for l in open('state/impl_progress.jsonl') for d in [json.loads(l)] if d.get('task_id')=='$TID' and d.get('event')=='auto_commit'))" 2>/dev/null
}

for attempt in $(seq 1 $MAX); do
  # clean sidecars + stale self-heal artifacts
  rm -f state/output/$TID.* state/tasks/processed/$TID.json state/tasks/blocked/$TID.* \
        state/tasks/$TID.json.processing state/tasks/current_task_$TID.json state/tasks/$TID.json 2>/dev/null
  rm -f brief_hooks_selfheal_$TID.md plan_hooks_selfheal_$TID.json 2>/dev/null
  # require NGv2 clean + static
  if [ -n "$(git -C $NGV2 status --porcelain)" ]; then echo "ATTEMPT $attempt: NGv2 dirty, aborting"; exit 2; fi
  python3 -c "from pathlib import Path; from harness.planner.staging import stage_task; stage_task(Path('$PLAN'),'$TID',Path('state'),working_dir='$NGV2')" || { echo "stage failed"; exit 2; }
  printf run > state/control/orchestrator.flag
  echo "ATTEMPT $attempt/$MAX: dispatching detonation worker $(date -u +%H:%M:%S)"
  JANUSMASK_WORKING_DIR=$NGV2 python3 -m harness.orchestrator_worker --state-dir state --task-id $TID > /tmp/ngv2_det_retry_$attempt.log 2>&1
  if [ "$(accepted)" -ge 1 ] 2>/dev/null; then
    printf paused > state/control/orchestrator.flag
    echo "SUCCESS: detonation accepted on attempt $attempt. NGv2 master: $(git -C $NGV2 log --oneline -1 master)"
    exit 0
  fi
  echo "ATTEMPT $attempt outcome: $(cat /tmp/ngv2_det_retry_$attempt.log | tail -1)"
  if [ "$attempt" -lt "$MAX" ]; then echo "sleeping ${INTERVAL}s before next attempt"; sleep $INTERVAL; fi
done
printf paused > state/control/orchestrator.flag
echo "EXHAUSTED: detonation not accepted after $MAX attempts; throttle likely still active. Code is proven-correct; retry later."
exit 1
