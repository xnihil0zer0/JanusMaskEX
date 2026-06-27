#!/bin/bash
cd /home/xnihil0zer0/JanusMaskJR
LEDGER=state/impl_progress.jsonl
BASE_LINES=$(wc -l < "$LEDGER")
BASE_HEAD=$(git rev-parse HEAD)
OURS='config-schema|model-backends|secrets-store'
DEADLINE=$(( $(date +%s) + 1500 ))
while :; do
  sleep 25
  NEWHEAD=$(git rev-parse HEAD)
  if [ "$NEWHEAD" != "$BASE_HEAD" ]; then
    NEWMSGS=$(git log --oneline "$BASE_HEAD".."$NEWHEAD")
    if echo "$NEWMSGS" | grep -qiE "Integrate validated code for ($OURS)"; then
      echo "WATCHER_EXIT=LANDED"; echo "$NEWMSGS"; break
    fi
  fi
  NEWROWS=$(tail -n +$((BASE_LINES+1)) "$LEDGER")
  REJECT=$(echo "$NEWROWS" | grep -E '"event": "(task_blocked|ast_validation_failed|verification_failed|retry_exhausted|dependency_failed)"' | grep -iE "$OURS")
  if [ -n "$REJECT" ]; then echo "WATCHER_EXIT=REJECTED"; echo "$REJECT" | tail -5; break; fi
  DISCARD=$(echo "$NEWROWS" | grep -E '"event": "planner_hallucination_discarded"' | grep -iE "$OURS")
  if [ -n "$DISCARD" ]; then echo "WATCHER_EXIT=PLAN_DISCARDED"; echo "$DISCARD" | tail -3; break; fi
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then echo "WATCHER_EXIT=STALL"; break; fi
done
echo "--- HEAD: $(git rev-parse --short HEAD) ---"
echo "--- last 6 real telemetry ---"
tail -n +$((BASE_LINES+1)) "$LEDGER" | grep -vE '"event": "(idle|active)"' | tail -6
echo "--- running ---"; ls state/control/autowork/running/ 2>/dev/null || echo none
